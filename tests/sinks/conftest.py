"""Fixtures compartilhadas pelos testes da trilha E (sinks, DD-02).

Sem `tests/__init__.py` no repositório, `tests` só é importável como pacote de
namespace se a raiz do repo estiver em `sys.path`. Este `conftest.py` é carregado
cedo pelo pytest (antes da coleta dos módulos de teste), então garantimos aqui,
só para os testes desta trilha, que os módulos-irmãos (`tests.sinks._db_fakes`,
`tests.sinks._kafka_fakes`) sejam importáveis por `from tests.sinks... import ...`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dataipsum.contracts.sink import RunContext  # noqa: E402
from dataipsum.schema.models import ColumnSpec, PrimaryKeySpec, Schema, TableSpec  # noqa: E402


def make_column(name: str, type_: str = "string", **kwargs: object) -> ColumnSpec:
    return ColumnSpec(name=name, type=type_, **kwargs)  # type: ignore[arg-type]


def make_table(
    name: str,
    columns: list[ColumnSpec],
    *,
    pk_columns: list[str] | None = None,
    rows: int = 10,
) -> TableSpec:
    return TableSpec(
        name=name,
        rows=rows,
        primary_key=PrimaryKeySpec(columns=pk_columns or ["id"], strategy="sequence", start=1),
        columns=columns,
    )


def make_run_context(
    out_dir: str,
    *,
    run_id: str = "11111111-1111-1111-1111-111111111111",
    schema: Schema | None = None,
) -> RunContext:
    return RunContext(run_id=run_id, out_dir=out_dir, seed=42, schema=schema)


def make_schema(tables: list[TableSpec], *, name: str = "dataipsum") -> Schema:
    return Schema(version=1, name=name, tables=tables)
