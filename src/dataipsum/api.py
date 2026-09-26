"""Façade pública da biblioteca (`dataipsum.api`, DD-00 §3.8).

Cada função delega a implementação real ao módulo da trilha responsável. `generate`/`resume`
são implementados pela integração do motor (DD-01 §S5, "troca os fakes pelas implementações
reais"): planner de `dataipsum.relations` (trilha B), `LocalExecutor` de `dataipsum.execution`
(trilha D) rodando `dataipsum.execution.worker.run_chunk` (que reconstrói `Registry`/`Sink`/motor
LLM real em cada worker) e o registry de `dataipsum.registry.build_registry` (tipos + relações +
LLM; **sinks reais não estão registrados ainda** — gap conhecido do DD-02, fora do escopo do S5).

`load_schema`/`validate` são wrappers finos sobre `dataipsum.schema.loader` (S2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dataipsum.config import RunOptions
from dataipsum.contracts.planner import RunPlan
from dataipsum.execution import orchestrator
from dataipsum.execution.local_executor import LocalExecutor
from dataipsum.execution.worker import run_chunk
from dataipsum.manifest import check_output_dir_for_generate
from dataipsum.relations import RelationsPlanner
from dataipsum.schema.loader import load_schema as _load_schema
from dataipsum.schema.loader import validate as _validate

if TYPE_CHECKING:
    from dataipsum.execution.orchestrator import OrchestratorResult
    from dataipsum.schema.loader import ValidationReport
    from dataipsum.schema.models import Schema

SchemaFormat = Literal["ddl", "avro"]

__all__ = [
    "RunOptions",
    "RunResult",
    "export_schema",
    "generate",
    "import_ddl",
    "load_schema",
    "plan",
    "resume",
    "validate",
]


@dataclass(frozen=True)
class RunResult:
    """Resultado de `generate`/`resume` (DD-00 §3.8)."""

    run_id: str
    status: str
    manifest_path: Path
    tables: dict[str, int]
    pending_chunks: int


def load_schema(source: Path | str | dict[str, object]) -> Schema:
    """Carrega e normaliza um schema a partir de um caminho, YAML/JSON em texto ou `dict`."""
    return _load_schema(source)


def validate(schema: Schema) -> ValidationReport:
    """Valida um schema já carregado, delegando ao registry (§3.3, validação em camadas)."""
    return _validate(schema)


def plan(schema: Schema, options: RunOptions) -> RunPlan:
    """Monta o `RunPlan` (tabelas em ordem topológica e seus chunks), via `RelationsPlanner`
    (trilha B)."""
    chunk_size = options.chunk_size or schema.chunk_size
    seed = options.seed if options.seed is not None else schema.seed
    if seed is None:
        from dataipsum import seeds as seeds_module

        seed = seeds_module.random_seed()
    return RelationsPlanner().plan(schema, seed, chunk_size)


def _to_run_result(result: OrchestratorResult) -> RunResult:
    return RunResult(
        run_id=result.run_id,
        status=result.status,
        manifest_path=result.manifest_path,
        tables=result.tables,
        pending_chunks=result.pending_chunks,
    )


def _new_executor() -> LocalExecutor:
    return LocalExecutor(run_chunk=run_chunk)


def generate(schema: Schema, options: RunOptions) -> RunResult:
    """Executa uma geração nova (DD-01 §S5): `RelationsPlanner` (trilha B) monta o `RunPlan` e
    `LocalExecutor` (trilha D) roda os chunks, cada um reconstruindo o `Registry`/`Sink`/motor
    LLM real a partir de `dataipsum.execution.worker.run_chunk`.

    O guardrail de diretório de saída (§6.4, critério 19) roda antes de qualquer outra coisa:
    `<out>` precisa estar inexistente ou vazio.
    """
    check_output_dir_for_generate(options.out_dir)
    executor = _new_executor()
    try:
        result = orchestrator.generate(
            schema, options, planner=RelationsPlanner(), executor=executor
        )
    finally:
        executor.shutdown(wait=True)
    return _to_run_result(result)


def resume(out_dir: Path, options: RunOptions) -> RunResult:
    """Retoma uma execução a partir do manifesto embutido em `out_dir` (DD-01 §S5)."""
    executor = _new_executor()
    try:
        result = orchestrator.resume(out_dir, options, executor=executor)
    finally:
        executor.shutdown(wait=True)
    return _to_run_result(result)


def export_schema(
    schema: Schema, format: SchemaFormat, dialect: str | None = None, *, out_dir: Path
) -> list[Path]:
    """Exporta o schema para DDL/Avro. Implementado na trilha F."""
    raise NotImplementedError("trilha F")


def import_ddl(sql_text: str, dialect: str) -> Schema:
    """Importa um `Schema` a partir de DDL SQL (M3). Implementado na trilha F."""
    raise NotImplementedError("trilha F")
