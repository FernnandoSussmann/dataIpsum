"""Testes do orquestrador (DD-01 §D.3.1, §D.6, §D.9): agendamento por grafo,
status final, retry/fatal, flush em lote, `emit_schema`, `resume`."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from dataipsum.config import RunOptions, SinkConfig
from dataipsum.contracts.executor import ChunkResult, ChunkTask
from dataipsum.contracts.planner import ChunkSpec, ParentRef, RunPlan, TablePlan
from dataipsum.errors import OutputDirError
from dataipsum.execution import orchestrator
from dataipsum.manifest import EmittedSchema, ManifestFlushPolicy, read_manifest
from dataipsum.schema.loader import load_schema
from dataipsum.testing.fakes import FakeExecutor


def _run_options(out_dir: Path, **overrides: Any) -> RunOptions:
    defaults: dict[str, Any] = {"out_dir": out_dir, "sink": SinkConfig(kind="fake")}
    defaults.update(overrides)
    return RunOptions(**defaults)


def _root_schema(table_rows: dict[str, int]) -> Any:
    return load_schema(
        {
            "version": 1,
            "name": "teste",
            "tables": [
                {
                    "name": name,
                    "rows": rows,
                    "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 0},
                    "columns": [{"name": "id", "type": "int"}],
                }
                for name, rows in table_rows.items()
            ],
        }
    )


def _child_schema() -> Any:
    return load_schema(
        {
            "version": 1,
            "name": "teste",
            "tables": [
                {
                    "name": "usuarios",
                    "rows": 20,
                    "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 0},
                    "columns": [{"name": "id", "type": "int"}],
                },
                {
                    "name": "produtos",
                    "rows": 20,
                    "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 0},
                    "columns": [{"name": "id", "type": "int"}],
                },
                {
                    "name": "pedidos",
                    "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 0},
                    "rows_from": {"via": "usuario_id", "relation": "one_to_many"},
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                    ],
                },
            ],
        }
    )


def _table_plan(chunk_rows: list[int], *, parent: str | None = None) -> TablePlan:
    chunks = []
    first_row = 0
    for chunk_id, rows in enumerate(chunk_rows):
        parent_ref = (
            ParentRef(table=parent, first_index=0, count=rows, first_child_offset=0)
            if parent is not None
            else None
        )
        chunks.append(ChunkSpec(id=chunk_id, first_row=first_row, rows=rows, parent=parent_ref))
        first_row += rows
    return TablePlan(rows=sum(chunk_rows), chunks=tuple(chunks))


def _always_done(task: ChunkTask) -> ChunkResult:
    return ChunkResult(
        table=task.table, chunk_id=task.chunk_spec.id, status="done", rows=task.chunk_spec.rows
    )


@dataclass
class _WaveRecordingExecutor:
    """Envolve `FakeExecutor` e grava, por chamada de `submit`, quais (tabela,
    chunk) foram submetidos juntos — usado para verificar D-09 (paralelismo por
    tabela) sem precisar de concorrência real entre processos."""

    run_chunk: Any
    waves: list[list[tuple[str, int]]] = field(default_factory=list)
    _inner: FakeExecutor = field(init=False)

    def __post_init__(self) -> None:
        self._inner = FakeExecutor(run_chunk=self.run_chunk)
        self._inner.set_concurrency(100)

    def submit(self, tasks: Any) -> Any:
        tasks = list(tasks)
        self.waves.append([(t.table, t.chunk_spec.id) for t in tasks])
        return self._inner.submit(tasks)

    def set_concurrency(self, n: int) -> None:
        self._inner.set_concurrency(n)

    @property
    def concurrency(self) -> int:
        return self._inner.concurrency

    def shutdown(self, wait: bool) -> None:
        self._inner.shutdown(wait=wait)

    def llm_limiter(self, provider_name: str, max_concurrency: int) -> Any:
        return self._inner.llm_limiter(provider_name, max_concurrency)


# --- D-09 / agendamento por grafo -------------------------------------------------


def test_tabelas_raiz_independentes_rodam_juntas_e_filha_espera(tmp_path: Path) -> None:
    schema = _child_schema()
    run_plan = RunPlan(
        order=("usuarios", "produtos", "pedidos"),
        tables={
            "usuarios": _table_plan([10, 10]),
            "produtos": _table_plan([10, 10]),
            "pedidos": _table_plan([5, 5], parent="usuarios"),
        },
    )
    executor = _WaveRecordingExecutor(run_chunk=_always_done)
    now = _initial_manifest(schema, run_plan, seed=1)

    result = orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path),
        executor=executor,
        manifest=now,
    )

    assert result.status == "completed"
    first_wave = set(executor.waves[0])
    assert first_wave == {("usuarios", 0), ("usuarios", 1), ("produtos", 0), ("produtos", 1)}
    later_tables = {table for wave in executor.waves[1:] for table, _chunk_id in wave}
    assert later_tables == {"pedidos"}


def _initial_manifest(schema: Any, run_plan: RunPlan, *, seed: int) -> Any:
    from dataipsum.manifest import Manifest, compute_schema_sha256

    schema_dict = schema.model_dump(mode="json")
    return Manifest(
        run_id="r1",
        dataipsum_version="0.1.0",
        created_at="now",
        updated_at="now",
        status="running",
        seed=seed,
        seed_source="user",
        chunk_size=10_000,
        schema=schema_dict,
        schema_sha256=compute_schema_sha256(schema_dict),
        sink={"kind": "fake", "options": {}},
        plan=run_plan.to_json_dict(),
        chunks=orchestrator._initial_chunk_entries(run_plan),
    )


# --- status final -----------------------------------------------------------------


def test_status_completed_quando_todos_os_chunks_terminam_done(tmp_path: Path) -> None:
    schema = _root_schema({"usuarios": 20})
    run_plan = RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10, 10])})
    executor = FakeExecutor(run_chunk=_always_done)
    executor.set_concurrency(10)
    manifest = _initial_manifest(schema, run_plan, seed=1)

    result = orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path),
        executor=executor,
        manifest=manifest,
    )

    assert result.status == "completed"
    assert result.pending_chunks == 0
    assert read_manifest(tmp_path).status == "completed"


def test_status_partial_com_chunk_pending_llm(tmp_path: Path) -> None:
    def run_chunk(task: ChunkTask) -> ChunkResult:
        status = "pending_llm" if task.chunk_spec.id == 0 else "done"
        return ChunkResult(
            table=task.table, chunk_id=task.chunk_spec.id, status=status, rows=task.chunk_spec.rows
        )

    schema = _root_schema({"usuarios": 20})
    run_plan = RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10, 10])})
    executor = FakeExecutor(run_chunk=run_chunk)
    executor.set_concurrency(10)
    manifest = _initial_manifest(schema, run_plan, seed=1)

    result = orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path),
        executor=executor,
        manifest=manifest,
    )

    assert result.status == "partial"


def test_status_failed_com_erro_fatal(tmp_path: Path) -> None:
    def run_chunk(task: ChunkTask) -> ChunkResult:
        raise OutputDirError("disco cheio")

    schema = _root_schema({"usuarios": 10})
    run_plan = RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10])})
    executor = FakeExecutor(run_chunk=run_chunk)
    manifest = _initial_manifest(schema, run_plan, seed=1)

    result = orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path),
        executor=executor,
        manifest=manifest,
    )

    assert result.status == "failed"
    assert read_manifest(tmp_path).status == "failed"


# --- retry --------------------------------------------------------------------------


def test_retry_ate_3_tentativas_depois_failed(tmp_path: Path) -> None:
    attempts: dict[int, int] = {}

    def flaky(task: ChunkTask) -> ChunkResult:
        attempts[task.chunk_spec.id] = attempts.get(task.chunk_spec.id, 0) + 1
        return ChunkResult(
            table=task.table, chunk_id=task.chunk_spec.id, status="failed", rows=0, error="boom"
        )

    schema = _root_schema({"usuarios": 10})
    run_plan = RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10])})
    executor = FakeExecutor(run_chunk=flaky)
    manifest = _initial_manifest(schema, run_plan, seed=1)

    result = orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path),
        executor=executor,
        manifest=manifest,
    )

    assert attempts[0] == 3
    entry = read_manifest(tmp_path).chunks["usuarios"]["0"]
    assert entry.status == "failed"
    assert entry.attempts == 3
    assert result.status == "partial"


def test_retry_recupera_apos_falha_transitoria(tmp_path: Path) -> None:
    attempts: dict[int, int] = {}

    def flaky_once(task: ChunkTask) -> ChunkResult:
        attempts[task.chunk_spec.id] = attempts.get(task.chunk_spec.id, 0) + 1
        if attempts[task.chunk_spec.id] == 1:
            return ChunkResult(
                table=task.table, chunk_id=task.chunk_spec.id, status="failed", rows=0, error="boom"
            )
        return ChunkResult(
            table=task.table, chunk_id=task.chunk_spec.id, status="done", rows=task.chunk_spec.rows
        )

    schema = _root_schema({"usuarios": 10})
    run_plan = RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10])})
    executor = FakeExecutor(run_chunk=flaky_once)
    manifest = _initial_manifest(schema, run_plan, seed=1)

    result = orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path),
        executor=executor,
        manifest=manifest,
    )

    assert result.status == "completed"
    assert attempts[0] == 2


# --- manifesto em lote ---------------------------------------------------------------


def test_manifesto_e_gravado_em_lote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_calls = []
    original = orchestrator.write_manifest_atomic

    def counting_write(out_dir: Path, manifest: Any) -> None:
        write_calls.append(manifest.status)
        original(out_dir, manifest)

    monkeypatch.setattr(orchestrator, "write_manifest_atomic", counting_write)

    schema = _root_schema({"usuarios": 100})
    run_plan = RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10] * 10)})
    executor = FakeExecutor(run_chunk=_always_done)
    executor.set_concurrency(10)
    manifest = _initial_manifest(schema, run_plan, seed=1)

    orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path),
        executor=executor,
        manifest=manifest,
        manifest_flush_policy=ManifestFlushPolicy(chunk_batch_size=1_000, interval_seconds=1_000),
    )

    # Com um lote gigante, só a escrita inicial e a final acontecem (não uma por chunk).
    assert len(write_calls) == 2


# --- emit_schema ----------------------------------------------------------------------


def test_emit_schema_e_chamado_quando_pedido(tmp_path: Path) -> None:
    schema = _root_schema({"usuarios": 10})
    run_plan = RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10])})
    executor = FakeExecutor(run_chunk=_always_done)
    manifest = _initial_manifest(schema, run_plan, seed=1)
    emitted = [EmittedSchema(format="ddl", path="_schema/usuarios.sql", sha256="abc")]

    orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path, emit_schema=("ddl",)),
        executor=executor,
        manifest=manifest,
        emit_schema_fn=lambda: emitted,
    )

    assert read_manifest(tmp_path).emitted_schemas == tuple(emitted)


def test_emit_schema_nao_e_chamado_sem_pedido(tmp_path: Path) -> None:
    schema = _root_schema({"usuarios": 10})
    run_plan = RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10])})
    executor = FakeExecutor(run_chunk=_always_done)
    manifest = _initial_manifest(schema, run_plan, seed=1)
    called = []

    orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path),
        executor=executor,
        manifest=manifest,
        emit_schema_fn=lambda: called.append(1) or [],
    )

    assert called == []


# --- Ctrl+C -----------------------------------------------------------------------


def test_ctrl_c_para_de_submeter_e_grava_partial(tmp_path: Path) -> None:
    stop_event = threading.Event()

    def stop_after_first(task: ChunkTask) -> ChunkResult:
        if task.chunk_spec.id == 0:
            stop_event.set()
        return ChunkResult(
            table=task.table, chunk_id=task.chunk_spec.id, status="done", rows=task.chunk_spec.rows
        )

    schema = _root_schema({"usuarios": 30})
    run_plan = RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10, 10, 10])})
    executor = FakeExecutor(run_chunk=stop_after_first)
    executor.set_concurrency(1)  # uma onda por chunk, para o Ctrl+C parar depois da 1ª
    manifest = _initial_manifest(schema, run_plan, seed=1)

    result = orchestrator._execute(
        schema=schema,
        run_plan=run_plan,
        root_seed=1,
        out_dir=tmp_path,
        sink=SinkConfig(kind="fake"),
        run_options=_run_options(tmp_path),
        executor=executor,
        manifest=manifest,
        stop_event=stop_event,
    )

    assert result.status == "partial"
    final = read_manifest(tmp_path)
    assert final.status == "partial"
    done = [e for e in final.chunks["usuarios"].values() if e.status == "done"]
    assert 1 <= len(done) < 3


# --- resume -------------------------------------------------------------------------


def test_resume_reexecuta_so_os_nao_done(tmp_path: Path) -> None:
    schema = _root_schema({"usuarios": 20})
    options = _run_options(tmp_path)
    calls: list[int] = []

    def run_chunk(task: ChunkTask) -> ChunkResult:
        calls.append(task.chunk_spec.id)
        if task.chunk_spec.id == 0:
            return ChunkResult(table=task.table, chunk_id=0, status="failed", rows=0, error="boom")
        return ChunkResult(
            table=task.table, chunk_id=task.chunk_spec.id, status="done", rows=task.chunk_spec.rows
        )

    class _StubPlanner:
        def plan(self, schema: Any, seed: int, chunk_size: int) -> RunPlan:
            return RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10, 10])})

    executor = FakeExecutor(run_chunk=run_chunk)
    orchestrator.generate(schema, options, planner=_StubPlanner(), executor=executor)
    # chunk 0 falha sempre: esgota as 3 tentativas dentro do próprio `generate`
    # (retomado só depois, no `resume`); chunk 1 termina na primeira tentativa.
    assert calls == [0, 1, 0, 0]

    calls.clear()

    def run_chunk_ok(task: ChunkTask) -> ChunkResult:
        calls.append(task.chunk_spec.id)
        return ChunkResult(
            table=task.table, chunk_id=task.chunk_spec.id, status="done", rows=task.chunk_spec.rows
        )

    executor2 = FakeExecutor(run_chunk=run_chunk_ok)
    result = orchestrator.resume(tmp_path, options, executor=executor2)

    assert calls == [0]  # só o chunk 0 (failed) é reexecutado; o 1 (done) não
    assert result.status == "completed"


def test_resume_llm_only_reexecuta_so_pending_llm(tmp_path: Path) -> None:
    schema = _root_schema({"usuarios": 20})
    options = _run_options(tmp_path)

    def run_chunk_mixed(task: ChunkTask) -> ChunkResult:
        status = "pending_llm" if task.chunk_spec.id == 0 else "done"
        return ChunkResult(
            table=task.table, chunk_id=task.chunk_spec.id, status=status, rows=task.chunk_spec.rows
        )

    class _StubPlanner:
        def plan(self, schema: Any, seed: int, chunk_size: int) -> RunPlan:
            return RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10, 10])})

    executor = FakeExecutor(run_chunk=run_chunk_mixed)
    orchestrator.generate(schema, options, planner=_StubPlanner(), executor=executor)

    calls: list[int] = []

    def run_chunk_done(task: ChunkTask) -> ChunkResult:
        calls.append(task.chunk_spec.id)
        return ChunkResult(
            table=task.table, chunk_id=task.chunk_spec.id, status="done", rows=task.chunk_spec.rows
        )

    executor2 = FakeExecutor(run_chunk=run_chunk_done)
    result = orchestrator.resume(tmp_path, options, executor=executor2, llm_only=True)

    assert calls == [0]
    assert result.status == "completed"


def test_resume_recusa_hash_de_schema_diferente(tmp_path: Path) -> None:
    schema = _root_schema({"usuarios": 10})
    options = _run_options(tmp_path)

    class _StubPlanner:
        def plan(self, schema: Any, seed: int, chunk_size: int) -> RunPlan:
            return RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10])})

    executor = FakeExecutor(run_chunk=_always_done)
    orchestrator.generate(schema, options, planner=_StubPlanner(), executor=executor)

    outro_schema = _root_schema({"usuarios": 999})
    with pytest.raises(Exception, match="schema"):
        orchestrator.resume(
            tmp_path, options, executor=FakeExecutor(run_chunk=_always_done), schema=outro_schema
        )


def test_resume_nao_replaneja(tmp_path: Path) -> None:
    """`resume` reusa o `RunPlan` gravado, sem chamar `Planner.plan` de novo."""
    schema = _root_schema({"usuarios": 10})
    options = _run_options(tmp_path)

    class _StubPlanner:
        def plan(self, schema: Any, seed: int, chunk_size: int) -> RunPlan:
            return RunPlan(order=("usuarios",), tables={"usuarios": _table_plan([10])})

    orchestrator.generate(
        schema, options, planner=_StubPlanner(), executor=FakeExecutor(run_chunk=_always_done)
    )
    plan_before = read_manifest(tmp_path).plan

    orchestrator.resume(tmp_path, options, executor=FakeExecutor(run_chunk=_always_done))
    plan_after = read_manifest(tmp_path).plan

    assert plan_before == plan_after
