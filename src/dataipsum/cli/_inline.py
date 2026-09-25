"""Geração rápida de uma tabela via flags `--col` (DD-02 §G.3.1, DD-00 §3.3).

O parsing das strings `nome:tipo[:pk][:chave=valor]` é de `build_inline_schema`
(DD-00). Este módulo só decide quando usar o modo inline em vez de um SCHEMA em
arquivo, recusa o tipo `ref` (relações exigem YAML) e formata `--print-schema`.
"""

from __future__ import annotations

from pathlib import Path

import typer
import yaml

from dataipsum import api
from dataipsum.errors import SchemaError, ValidationError
from dataipsum.schema.inline import build_inline_schema
from dataipsum.schema.models import Schema

_RELATION_TYPE = "ref"


def _column_type(raw_column: str) -> str:
    parts = raw_column.split(":")
    return parts[1] if len(parts) > 1 else ""


def _reject_relations(cols: list[str]) -> None:
    relation_columns = [raw for raw in cols if _column_type(raw) == _RELATION_TYPE]
    if relation_columns:
        raise SchemaError(
            [
                ValidationError(
                    path="cols",
                    message=(
                        "colunas do tipo 'ref' definem relações entre tabelas, que só podem "
                        "ser expressas num schema YAML completo, não nas flags --col inline"
                    ),
                )
                for _ in relation_columns
            ]
        )


def build_schema_from_inline_flags(table: str, rows: int, cols: list[str]) -> Schema:
    _reject_relations(cols)
    return build_inline_schema(table, rows, cols)


def dump_schema_yaml(schema: Schema) -> str:
    return yaml.safe_dump(
        schema.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True
    )


def print_schema_and_exit(schema: Schema) -> typer.Exit:
    typer.echo(dump_schema_yaml(schema))
    return typer.Exit(code=0)


def load_schema_from_source(
    schema_path: Path | None, table: str | None, rows: int | None, cols: list[str]
) -> Schema:
    """Resolve o `Schema` a partir de SCHEMA (arquivo) ou de `--table`/`--rows`/`--col`."""
    using_inline = table is not None or cols
    if schema_path is not None and using_inline:
        raise SchemaError(
            [
                ValidationError(
                    path="$",
                    message=(
                        "use SCHEMA (arquivo) OU --table/--col (inline), não os dois ao mesmo tempo"
                    ),
                )
            ]
        )
    if schema_path is not None:
        return api.load_schema(schema_path)
    if table is None or rows is None:
        raise SchemaError(
            [
                ValidationError(
                    path="$",
                    message=(
                        "informe SCHEMA (arquivo YAML/JSON) ou os três de --table, --rows e "
                        "--col para geração inline de uma tabela"
                    ),
                )
            ]
        )
    return build_schema_from_inline_flags(table, rows, cols)
