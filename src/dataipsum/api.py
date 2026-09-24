"""Façade pública da biblioteca (`dataipsum.api`, DD-00 §3.8).

Cada função delega a implementação real ao módulo da trilha responsável e,
enquanto essa trilha não existe, levanta `NotImplementedError("trilha X")`
(ver a coluna "Responsável" da tabela do §3.8). `generate` é a única exceção
parcial: o guardrail de diretório de saída (§6.4) precisa valer mesmo antes
da trilha D existir, então ele roda antes do `NotImplementedError`.

`load_schema`/`validate` são wrappers finos sobre `dataipsum.schema.loader`
(S2). Eles são importados por nome no topo do módulo, como o contrato entre
steps do DD-00 exige — este módulo (S4) é escrito e testado antes de S2/S3
existirem neste worktree, então esse import só resolve depois do merge.
Os testes deste módulo tratam `dataipsum.schema.loader`, `dataipsum.seeds`
e `dataipsum.config` como uma costura substituível (ver `tests/core/unit/conftest.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dataipsum.config import RunOptions
from dataipsum.contracts.planner import RunPlan
from dataipsum.manifest import check_output_dir_for_generate
from dataipsum.schema.loader import load_schema as _load_schema
from dataipsum.schema.loader import validate as _validate

if TYPE_CHECKING:
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
    """Monta o `RunPlan` (tabelas em ordem topológica e seus chunks). Implementado na trilha B."""
    raise NotImplementedError("trilha B")


def generate(schema: Schema, options: RunOptions) -> RunResult:
    """Executa uma geração nova. Implementado na trilha D.

    O guardrail de diretório de saída (§6.4, critério 19) roda antes de
    qualquer outra coisa: `<out>` precisa estar inexistente ou vazio, mesmo
    enquanto a trilha D ainda não existe.
    """
    check_output_dir_for_generate(options.out_dir)
    raise NotImplementedError("trilha D")


def resume(out_dir: Path, options: RunOptions) -> RunResult:
    """Retoma uma execução a partir do manifesto embutido em `out_dir`. Implementado na trilha D."""
    raise NotImplementedError("trilha D")


def export_schema(
    schema: Schema, format: SchemaFormat, dialect: str | None = None, *, out_dir: Path
) -> list[Path]:
    """Exporta o schema para DDL/Avro. Implementado na trilha F."""
    raise NotImplementedError("trilha F")


def import_ddl(sql_text: str, dialect: str) -> Schema:
    """Importa um `Schema` a partir de DDL SQL (M3). Implementado na trilha F."""
    raise NotImplementedError("trilha F")
