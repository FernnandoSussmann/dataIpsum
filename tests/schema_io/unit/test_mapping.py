"""Testes diretos de `logical_type_for_column` (DD-00 §3.5, DD-02 §F.3.1/F.3.2)."""

from __future__ import annotations

import pytest

from conftest import build_schema
from dataipsum.errors import SchemaError
from dataipsum.schema_io.mapping import find_table, logical_type_for_column

_LLM_CONFIG = {
    "default_provider": "local",
    "providers": {"local": {"kind": "ollama", "model": "llama3.1:8b"}},
}


def _single_column_schema(column: dict[str, object]) -> tuple[object, object, object]:
    document: dict[str, object] = {
        "version": 1,
        "tables": [
            {
                "name": "t",
                "rows": 1,
                "primary_key": {"columns": ["id"], "strategy": "sequence"},
                "columns": [{"name": "id", "type": "int"}, column],
            }
        ],
    }
    if str(column.get("type", "")).startswith("llm_"):
        document["llm"] = _LLM_CONFIG
    schema = build_schema(document)
    table = schema.tables[0]
    imported_column = next(c for c in table.columns if c.name == column["name"])
    return schema, table, imported_column


def test_string_sem_max_length_e_erro() -> None:
    schema, table, column = _single_column_schema({"name": "c", "type": "string"})
    with pytest.raises(SchemaError, match="max_length"):
        logical_type_for_column(schema, table, column)


def test_array_sem_item_e_erro() -> None:
    schema, table, column = _single_column_schema({"name": "c", "type": "array", "params": {}})
    with pytest.raises(SchemaError, match="params.item"):
        logical_type_for_column(schema, table, column)


def test_tipo_desconhecido_e_erro() -> None:
    schema, table, column = _single_column_schema({"name": "c", "type": "nao_existe"})
    with pytest.raises(SchemaError, match="não tem mapeamento"):
        logical_type_for_column(schema, table, column)


def test_find_table_inexistente_e_erro() -> None:
    schema, _, _ = _single_column_schema({"name": "c", "type": "int"})
    with pytest.raises(SchemaError):
        find_table(schema, "nao_existe")


def test_ref_para_pk_uuid_herda_kind_uuid() -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "produtos",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "seeded_uuid"},
                    "columns": [{"name": "id", "type": "uuid"}],
                },
                {
                    "name": "pedidos",
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "rows_from": {
                        "via": "produto_id",
                        "relation": "one_to_many",
                        "cardinality": {"range": {"min": 0, "max": 5}},
                    },
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "produto_id", "type": "ref", "params": {"table": "produtos"}},
                    ],
                },
            ],
        }
    )
    table = schema.tables[1]
    column = table.columns[1]
    logical_type = logical_type_for_column(schema, table, column)
    assert logical_type.kind == "uuid"


def test_llm_com_max_length_vira_string() -> None:
    schema, table, column = _single_column_schema(
        {"name": "c", "type": "llm_post", "max_length": 300}
    )
    logical_type = logical_type_for_column(schema, table, column)
    assert logical_type.kind == "string"
    assert logical_type.max_length == 300


def test_llm_sem_max_length_vira_text() -> None:
    schema, table, column = _single_column_schema({"name": "c", "type": "llm_post"})
    logical_type = logical_type_for_column(schema, table, column)
    assert logical_type.kind == "text"


def test_nullable_reflete_null_ratio() -> None:
    schema, table, column = _single_column_schema({"name": "c", "type": "int", "null_ratio": 0.2})
    assert logical_type_for_column(schema, table, column).nullable is True
