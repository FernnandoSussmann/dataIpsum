"""Testes de `avro_schema` (DD-02 §F.3.2, §F.6)."""

from __future__ import annotations

import fastavro
import pytest

from conftest import build_schema
from dataipsum.schema.models import Schema
from dataipsum.schema_io import avro_schema


def _field(schema_dict: dict[str, object], name: str) -> dict[str, object]:
    fields = schema_dict["fields"]
    assert isinstance(fields, list)
    return next(f for f in fields if f["name"] == name)


def test_namespace_e_nome_do_record(loja_schema: Schema) -> None:
    avsc = avro_schema(loja_schema, "usuarios")
    assert avsc["type"] == "record"
    assert avsc["name"] == "usuarios"
    assert avsc["namespace"] == "dataipsum.loja"


@pytest.mark.parametrize("table_name", ["usuarios", "produtos", "pedidos"])
def test_fastavro_aceita_o_schema(loja_schema: Schema, table_name: str) -> None:
    fastavro.parse_schema(avro_schema(loja_schema, table_name))


def test_coluna_anulavel_vira_union_com_default_null(loja_schema: Schema) -> None:
    avsc = avro_schema(loja_schema, "usuarios")
    bio_field = _field(avsc, "bio")
    assert bio_field["type"] == ["null", "string"]
    assert bio_field["default"] is None


def test_coluna_obrigatoria_nao_vira_union(loja_schema: Schema) -> None:
    avsc = avro_schema(loja_schema, "usuarios")
    nome_field = _field(avsc, "nome")
    assert nome_field["type"] == "string"
    assert "default" not in nome_field


def test_pk_recebe_doc(loja_schema: Schema) -> None:
    avsc = avro_schema(loja_schema, "usuarios")
    assert _field(avsc, "id")["doc"] == "PK"


def test_fk_recebe_doc_com_seta(loja_schema: Schema) -> None:
    avsc = avro_schema(loja_schema, "pedidos")
    doc = _field(avsc, "usuario_id")["doc"]
    assert doc == "FK → usuarios.id"


@pytest.mark.parametrize(
    ("column", "expected_type"),
    [
        ({"name": "c", "type": "int"}, "long"),
        ({"name": "c", "type": "float"}, "double"),
        ({"name": "c", "type": "boolean"}, "boolean"),
        ({"name": "c", "type": "text"}, "string"),
        ({"name": "c", "type": "json"}, "string"),
    ],
)
def test_mapeamento_de_tipos_simples(column: dict[str, object], expected_type: str) -> None:
    schema = build_schema(
        {
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
    )
    avsc = avro_schema(schema, "t")
    assert _field(avsc, "c")["type"] == expected_type


def test_date_time_timestamp_uuid_usam_logical_type() -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "t",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "d", "type": "date"},
                        {"name": "h", "type": "time"},
                        {"name": "ts", "type": "timestamp"},
                        {"name": "u", "type": "uuid"},
                    ],
                }
            ],
        }
    )
    avsc = avro_schema(schema, "t")
    assert _field(avsc, "d")["type"] == {"type": "int", "logicalType": "date"}
    assert _field(avsc, "h")["type"] == {"type": "int", "logicalType": "time-millis"}
    assert _field(avsc, "ts")["type"] == {"type": "long", "logicalType": "timestamp-millis"}
    assert _field(avsc, "u")["type"] == {"type": "string", "logicalType": "uuid"}
    fastavro.parse_schema(avsc)


def test_decimal_usa_logical_type_com_precisao_e_escala() -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "t",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [
                        {"name": "id", "type": "int"},
                        {
                            "name": "preco",
                            "type": "decimal",
                            "params": {"precision": 8, "scale": 3},
                        },
                    ],
                }
            ],
        }
    )
    avsc = avro_schema(schema, "t")
    assert _field(avsc, "preco")["type"] == {
        "type": "bytes",
        "logicalType": "decimal",
        "precision": 8,
        "scale": 3,
    }
    fastavro.parse_schema(avsc)


def test_array_vira_items_recursivo() -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "t",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [
                        {"name": "id", "type": "int"},
                        {
                            "name": "tags",
                            "type": "array",
                            "params": {"item": {"type": "string", "max_length": 10}},
                        },
                    ],
                }
            ],
        }
    )
    avsc = avro_schema(schema, "t")
    assert _field(avsc, "tags")["type"] == {"type": "array", "items": "string"}
    fastavro.parse_schema(avsc)
