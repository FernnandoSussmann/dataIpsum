"""Orquestrador: plano -> tarefas -> executor -> sink -> manifesto (DD-01 §D.3.1).

`generate`/`resume` montam o `Manifest` inicial e delegam o agendamento a
`_execute`, que:
- calcula o grafo de dependências entre tabelas (`execution.graph`) e libera uma
  tabela quando todas as tabelas das quais ela depende terminaram a primeira
  passada (`done`, `pending_llm`, `failed` ou `pending` com `blocked_by`);
- submete os chunks prontos em ondas do tamanho da concorrência corrente
  (`executor.concurrency`), o que respeita "em_voo <= concorrência" sem exigir que
  o `Executor` saiba cancelar tarefas em voo;
- reenvia um chunk com falha não fatal até 3 tentativas antes de marcá-lo
  `failed`; uma exceção fatal (`OutputDirError`, `ManifestError`, `OSError` de disco
  cheio) propaga do `Executor` e interrompe a execução imediatamente;
- para de submeter, espera até 10s pela onda em voo e grava o manifesto `partial`
  quando `stop_event` é sinalizado (Ctrl+C, DD-01 §D.5).
"""

from __future__ import annotations

import dataclasses
import errno
import importlib.metadata
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from dataipsum import seeds as seeds_module
from dataipsum.contracts.executor import ChunkTask
from dataipsum.errors import ManifestError, OutputDirError
from dataipsum.execution import graph as graph_module
from dataipsum.execution.plan_io import run_plan_from_json_dict
from dataipsum.manifest import (
    Manifest,
    ManifestChunkEntry,
    ManifestFlushPolicy,
    check_output_dir_for_generate,
    compute_schema_sha256,
    raise_if_major_version_mismatch,
    raise_if_schema_mismatch,
    read_manifest,
    write_manifest_atomic,
)
from dataipsum.schema.loader import load_schema

if TYPE_CHECKING:
    from collections.abc import Callable
    from threading import Event

    from dataipsum.config import RunOptions, SinkConfig
    from dataipsum.contracts.executor import ChunkResult, Executor
    from dataipsum.contracts.planner import ChunkSpec, Planner, RunPlan
    from dataipsum.execution.resources import ResourceMonitor
    from dataipsum.manifest import EmittedSchema, ManifestStatus, SeedSource
    from dataipsum.schema.models import Schema

logger = logging.getLogger("dataipsum.execution.orchestrator")

DEFAULT_MAX_ATTEMPTS_PER_CHUNK = 3
INTERRUPT_GRACE_PERIOD_SECONDS = 10.0
_FATAL_EXCEPTIONS: tuple[type[Exception], ...] = (OutputDirError, ManifestError)


def _dataipsum_version() -> str:
    return importlib.metadata.version("dataipsum")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_run_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class OrchestratorResult:
    """Espelha `dataipsum.api.RunResult` (DD-00 §3.8); `api.py` converte para o
    tipo público sem que este módulo precise importar `dataipsum.api` (evitaria um
    ciclo, já que `api.py` importa este módulo)."""

    run_id: str
    status: str
    manifest_path: Path
    tables: dict[str, int]
    pending_chunks: int


@dataclass
class _TableRuntimeState:
    queue: deque[ChunkTask]
    unresolved: int


def _run_options_payload(run_options: RunOptions) -> dict[str, object]:
    return {
        "llm_on_failure": run_options.llm_on_failure,
        "cache_dir": str(run_options.cache_dir) if run_options.cache_dir else None,
        "dialect": run_options.dialect,
    }


def _build_task(
    schema: Schema,
    table_name: str,
    chunk: ChunkSpec,
    root_seed: int,
    sink: SinkConfig,
    run_options: RunOptions,
) -> ChunkTask:
    return ChunkTask(
        table=table_name,
        chunk_spec=chunk,
        schema=schema,
        root_seed=root_seed,
        sink_options={"kind": sink.kind, "options": dict(sink.options)},
        run_options=_run_options_payload(run_options),
    )


def _needs_run(entry: ManifestChunkEntry | None, *, only_llm: bool) -> bool:
    if entry is None:
        return not only_llm
    if only_llm:
        return entry.status == "pending_llm"
    return entry.status in ("pending", "failed", "pending_llm") and not entry.blocked_by


def _is_resolved(entry: ManifestChunkEntry | None) -> bool:
    if entry is None:
        return False
    if entry.status in ("done", "pending_llm", "failed"):
        return True
    return entry.status == "pending" and bool(entry.blocked_by)


def _initial_chunk_entries(run_plan: RunPlan) -> dict[str, dict[str, ManifestChunkEntry]]:
    return {
        table_name: {
            str(chunk.id): ManifestChunkEntry(status="pending", rows=chunk.rows, attempts=0)
            for chunk in table_plan.chunks
        }
        for table_name, table_plan in run_plan.tables.items()
    }


def _build_table_states(
    schema: Schema,
    run_plan: RunPlan,
    manifest: Manifest,
    root_seed: int,
    sink: SinkConfig,
    run_options: RunOptions,
    *,
    only_llm: bool,
) -> dict[str, _TableRuntimeState]:
    states: dict[str, _TableRuntimeState] = {}
    for table_name, table_plan in run_plan.tables.items():
        entries = manifest.chunks.get(table_name, {})
        pending_chunks = [
            chunk
            for chunk in table_plan.chunks
            if _needs_run(entries.get(str(chunk.id)), only_llm=only_llm)
        ]
        tasks = deque(
            _build_task(schema, table_name, chunk, root_seed, sink, run_options)
            for chunk in pending_chunks
        )
        states[table_name] = _TableRuntimeState(queue=tasks, unresolved=len(tasks))
    return states


def _resolved_tables_from_manifest(run_plan: RunPlan, manifest: Manifest) -> set[str]:
    return {
        table_name
        for table_name, table_plan in run_plan.tables.items()
        if all(
            _is_resolved(manifest.chunks.get(table_name, {}).get(str(chunk.id)))
            for chunk in table_plan.chunks
        )
    }


def _record_result(
    manifest: Manifest,
    states: dict[str, _TableRuntimeState],
    attempts_this_run: dict[tuple[str, int], int],
    task: ChunkTask,
    result: ChunkResult,
    max_attempts: int,
) -> None:
    """Atualiza o manifesto com o resultado de um chunk. `attempts_this_run` conta
    só as tentativas desta chamada de `_execute`: um `resume` dá a cada chunk um
    novo orçamento de `max_attempts` tentativas, em vez de herdar o contador de uma
    execução anterior (senão um chunk `failed` reexecutado por `resume` já nasceria
    esgotado)."""
    table_chunks = manifest.chunks.setdefault(result.table, {})
    key = str(result.chunk_id)
    attempt_key = (result.table, result.chunk_id)
    attempts = attempts_this_run.get(attempt_key, 0) + 1
    attempts_this_run[attempt_key] = attempts
    state = states[result.table]

    if result.status == "failed" and attempts < max_attempts:
        table_chunks[key] = ManifestChunkEntry(
            status="pending", rows=result.rows, attempts=attempts
        )
        state.queue.append(task)
        return

    table_chunks[key] = ManifestChunkEntry(
        status=result.status,
        rows=result.rows,
        attempts=attempts,
        sink_ref=result.sink_ref,
        sha256=result.sha256,
        flags=result.flags,
        blocked_by=result.blocked_by,
        error=result.error,
    )
    state.unresolved -= 1


def _final_status(manifest: Manifest, *, interrupted: bool, fatal: bool) -> ManifestStatus:
    if fatal:
        return "failed"
    all_done = all(
        entry.status == "done" for table in manifest.chunks.values() for entry in table.values()
    )
    if all_done and not interrupted:
        return "completed"
    return "partial"


def _pending_chunk_count(manifest: Manifest) -> int:
    return sum(
        1
        for table in manifest.chunks.values()
        for entry in table.values()
        if entry.status != "done"
    )


def _execute(
    *,
    schema: Schema,
    run_plan: RunPlan,
    root_seed: int,
    out_dir: Path,
    sink: SinkConfig,
    run_options: RunOptions,
    executor: Executor,
    manifest: Manifest,
    only_llm: bool = False,
    emit_schema_fn: Callable[[], list[EmittedSchema]] | None = None,
    resource_monitor: ResourceMonitor | None = None,
    stop_event: Event | None = None,
    max_attempts_per_chunk: int = DEFAULT_MAX_ATTEMPTS_PER_CHUNK,
    manifest_flush_policy: ManifestFlushPolicy = ManifestFlushPolicy(),
    clock: Callable[[], float] = time.monotonic,
    now_iso: Callable[[], str] = _utc_now_iso,
) -> OrchestratorResult:
    dep_graph = graph_module.dependency_graph(schema)
    if run_options.emit_schema and emit_schema_fn is not None:
        manifest = dataclasses.replace(manifest, emitted_schemas=tuple(emit_schema_fn()))

    states = _build_table_states(
        schema, run_plan, manifest, root_seed, sink, run_options, only_llm=only_llm
    )
    resolved = _resolved_tables_from_manifest(run_plan, manifest)
    attempts_this_run: dict[tuple[str, int], int] = {}

    write_manifest_atomic(out_dir, manifest)
    chunks_since_flush = 0
    last_flush = clock()
    fatal = False
    interrupted = False

    while True:
        if stop_event is not None and stop_event.is_set():
            interrupted = True
            break

        # Uma tabela está "desbloqueada" quando todas as tabelas das quais ela
        # depende já terminaram a primeira passada (`resolved`) — mesmo que a
        # própria tabela também esteja em `resolved` (ela já pode ter chunks
        # `pending_llm`/`failed` retomáveis, ex.: `resume --llm-only`).
        unlocked = frozenset(
            name for name, deps in dep_graph.items() if deps <= frozenset(resolved)
        )

        concurrency = (
            0
            if (resource_monitor is not None and resource_monitor.paused)
            else max(1, executor.concurrency)
        )
        wave: list[ChunkTask] = []
        for table_name in run_plan.order:
            if table_name not in unlocked:
                continue
            queue = states[table_name].queue
            while queue and len(wave) < concurrency:
                wave.append(queue.popleft())

        if not wave:
            if all(state.unresolved == 0 for state in states.values()):
                break
            if concurrency == 0:
                time.sleep(0.05)
                continue
            break  # nada pronto para submeter e nada em voo: evita laço infinito

        deadline = clock() + INTERRUPT_GRACE_PERIOD_SECONDS
        try:
            for result in executor.submit(wave):
                task = next(
                    t
                    for t in wave
                    if t.table == result.table and t.chunk_spec.id == result.chunk_id
                )
                _record_result(
                    manifest, states, attempts_this_run, task, result, max_attempts_per_chunk
                )
                chunks_since_flush += 1
                if stop_event is not None and stop_event.is_set() and clock() >= deadline:
                    interrupted = True
                    break
        except _FATAL_EXCEPTIONS as exc:
            logger.error("erro fatal, interrompendo a execução: %s", exc)
            fatal = True
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                logger.error("disco cheio, interrompendo a execução: %s", exc)
                fatal = True
            else:
                raise

        for table_name in unlocked:
            if states[table_name].unresolved == 0:
                resolved.add(table_name)

        now = clock()
        if manifest_flush_policy.should_flush(chunks_since_flush, now - last_flush):
            manifest = dataclasses.replace(manifest, updated_at=now_iso())
            write_manifest_atomic(out_dir, manifest)
            chunks_since_flush = 0
            last_flush = now

        if fatal or interrupted:
            break

    manifest = dataclasses.replace(
        manifest,
        status=_final_status(manifest, interrupted=interrupted, fatal=fatal),
        updated_at=now_iso(),
    )
    write_manifest_atomic(out_dir, manifest)

    return OrchestratorResult(
        run_id=manifest.run_id,
        status=manifest.status,
        manifest_path=out_dir / "_manifest.json",
        tables={name: plan.rows for name, plan in run_plan.tables.items()},
        pending_chunks=_pending_chunk_count(manifest),
    )


def generate(
    schema: Schema,
    options: RunOptions,
    *,
    planner: Planner,
    executor: Executor,
    emit_schema_fn: Callable[[], list[EmittedSchema]] | None = None,
    resource_monitor: ResourceMonitor | None = None,
    stop_event: Event | None = None,
    max_attempts_per_chunk: int = DEFAULT_MAX_ATTEMPTS_PER_CHUNK,
    manifest_flush_policy: ManifestFlushPolicy = ManifestFlushPolicy(),
) -> OrchestratorResult:
    """Executa uma geração nova (DD-01 §D.3.1)."""
    check_output_dir_for_generate(options.out_dir)

    seed = options.seed if options.seed is not None else seeds_module.random_seed()
    seed_source: SeedSource = "user" if options.seed is not None else "random"
    chunk_size = options.chunk_size or schema.chunk_size
    run_plan = planner.plan(schema, seed, chunk_size)

    schema_dict = schema.model_dump(mode="json")
    now = _utc_now_iso()
    manifest = Manifest(
        run_id=_new_run_id(),
        dataipsum_version=_dataipsum_version(),
        created_at=now,
        updated_at=now,
        status="running",
        seed=seed,
        seed_source=seed_source,
        chunk_size=chunk_size,
        schema=schema_dict,
        schema_sha256=compute_schema_sha256(schema_dict),
        sink={"kind": options.sink.kind, "options": dict(options.sink.options)},
        plan=run_plan.to_json_dict(),
        chunks=_initial_chunk_entries(run_plan),
    )

    return _execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=seed,
        out_dir=options.out_dir,
        sink=options.sink,
        run_options=options,
        executor=executor,
        manifest=manifest,
        emit_schema_fn=emit_schema_fn,
        resource_monitor=resource_monitor,
        stop_event=stop_event,
        max_attempts_per_chunk=max_attempts_per_chunk,
        manifest_flush_policy=manifest_flush_policy,
    )


def resume(
    out_dir: Path,
    options: RunOptions,
    *,
    executor: Executor,
    schema: Schema | None = None,
    llm_only: bool = False,
    resource_monitor: ResourceMonitor | None = None,
    stop_event: Event | None = None,
    max_attempts_per_chunk: int = DEFAULT_MAX_ATTEMPTS_PER_CHUNK,
    manifest_flush_policy: ManifestFlushPolicy = ManifestFlushPolicy(),
) -> OrchestratorResult:
    """Retoma uma execução a partir do manifesto (DD-01 §D.3.5). Não replaneja:
    reusa o `RunPlan` e a seed gravados. `schema`, quando fornecido, é comparado
    por hash ao schema do manifesto (uso do CLI de `dataipsum resume --schema`,
    trilha G; `api.resume` não tem esse parâmetro, então passa `None`)."""
    manifest = read_manifest(out_dir)
    raise_if_major_version_mismatch(manifest.dataipsum_version, _dataipsum_version())
    if schema is not None:
        raise_if_schema_mismatch(
            manifest.schema_sha256, compute_schema_sha256(schema.model_dump(mode="json"))
        )

    manifest_schema = load_schema(manifest.schema)
    run_plan = run_plan_from_json_dict(manifest.plan)
    manifest = dataclasses.replace(manifest, status="running")

    return _execute(
        schema=manifest_schema,
        run_plan=run_plan,
        root_seed=manifest.seed,
        out_dir=out_dir,
        sink=options.sink,
        run_options=options,
        executor=executor,
        manifest=manifest,
        only_llm=llm_only,
        resource_monitor=resource_monitor,
        stop_event=stop_event,
        max_attempts_per_chunk=max_attempts_per_chunk,
        manifest_flush_policy=manifest_flush_policy,
    )
