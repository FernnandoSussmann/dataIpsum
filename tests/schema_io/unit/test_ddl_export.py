"""Testes de `ddl_for` (DD-02 §F.3.1, §F.6)."""

from __future__ import annotations

import re

import pytest
import sqlglot

from conftest import build_schema
from dataipsum.errors import SchemaError
from dataipsum.schema.models import Schema
from dataipsum.schema_io import ddl_for


def _statement_for(sql: str, table_name: str) -> str:
    match = re.search(rf'CREATE TABLE "?{table_name}"?[^;]*;', sql) or re.search(
        rf"CREATE TABLE `{table_name}`[^;]*;", sql
    )
    assert match is not None, f"tabela '{table_name}' não encontrada em: {sql}"
    return match.group(0)


@pytest.mark.parametrize("dialect", ["postgres", "mysql"])
def test_ddl_reparseia_no_mesmo_dialeto(loja_schema: Schema, dialect: str) -> None:
    sql = ddl_for(loja_schema, dialect)
    statements = sqlglot.parse(sql, read=dialect)
    assert len(statements) == len(loja_schema.tables)


def test_ordem_topologica_pai_antes_do_filho(loja_schema: Schema) -> None:
    sql = ddl_for(loja_schema, "postgres")
    assert sql.index('CREATE TABLE "usuarios"') < sql.index('CREATE TABLE "pedidos"')
    assert sql.index('CREATE TABLE "produtos"') < sql.index('CREATE TABLE "pedidos"')


def test_fk_inline_referencia_tabela_pai(loja_schema: Schema) -> None:
    sql = ddl_for(loja_schema, "postgres")
    pedidos = _statement_for(sql, "pedidos")
    assert 'FOREIGN KEY ("usuario_id") REFERENCES "usuarios" ("id")' in pedidos
    assert 'FOREIGN KEY ("produto_id") REFERENCES "produtos" ("id")' in pedidos


def test_not_null_reflete_null_ratio_zero(loja_schema: Schema) -> None:
    sql = ddl_for(loja_schema, "postgres")
    usuarios = _statement_for(sql, "usuarios")
    assert '"nome" VARCHAR(120) NOT NULL' in usuarios
    assert '"bio" VARCHAR(200)' in usuarios
    assert '"bio" VARCHAR(200) NOT NULL' not in usuarios


def test_varchar_usa_max_length_declarado(loja_schema: Schema) -> None:
    sql = ddl_for(loja_schema, "postgres")
    assert '"titulo" VARCHAR(80)' in _statement_for(sql, "produtos")


def test_cpf_vira_char_14_quando_masked(loja_schema: Schema) -> None:
    sql = ddl_for(loja_schema, "postgres")
    assert '"cpf" CHAR(14) NOT NULL' in _statement_for(sql, "usuarios")


def test_cpf_vira_char_11_quando_unmasked() -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "clientes",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "cpf", "type": "cpf", "format": "unmasked"},
                    ],
                }
            ],
        }
    )
    sql = ddl_for(schema, "postgres")
    assert '"cpf" CHAR(11) NOT NULL' in sql


def test_pk_composta() -> None:
    bridge_schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "lojas",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [{"name": "id", "type": "int"}],
                },
                {
                    "name": "categorias",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [{"name": "id", "type": "int"}],
                },
                {
                    "name": "loja_categoria",
                    "primary_key": {
                        "columns": ["loja_id", "categoria_id"],
                        "strategy": "composite",
                    },
                    "rows_from": {
                        "via": "loja_id",
                        "relation": "many_to_many",
                        "pair": "categoria_id",
                        "cardinality": {"range": {"min": 1, "max": 3}},
                    },
                    "columns": [
                        {"name": "loja_id", "type": "ref", "params": {"table": "lojas"}},
                        {"name": "categoria_id", "type": "ref", "params": {"table": "categorias"}},
                    ],
                },
            ],
        }
    )
    sql = ddl_for(bridge_schema, "postgres")
    assert 'PRIMARY KEY ("loja_id", "categoria_id")' in _statement_for(sql, "loja_categoria")


def test_unique_em_one_to_one() -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "usuarios",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [{"name": "id", "type": "int"}],
                },
                {
                    "name": "perfis",
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "rows_from": {
                        "via": "usuario_id",
                        "relation": "one_to_one",
                        "coverage": 1.0,
                    },
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                    ],
                },
            ],
        }
    )
    sql = ddl_for(schema, "postgres")
    assert '"usuario_id" BIGINT NOT NULL UNIQUE' in _statement_for(sql, "perfis")


def test_identificador_reservado_e_quotado() -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "order",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [{"name": "id", "type": "int"}, {"name": "user", "type": "int"}],
                }
            ],
        }
    )
    postgres_sql = ddl_for(schema, "postgres")
    mysql_sql = ddl_for(schema, "mysql")
    assert '"order"' in postgres_sql and '"user"' in postgres_sql
    assert "`order`" in mysql_sql and "`user`" in mysql_sql


def test_dialeto_nao_testado_emite_aviso() -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "t",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [{"name": "id", "type": "int"}],
                }
            ],
        }
    )
    with pytest.warns(UserWarning, match="não é testado"):
        ddl_for(schema, "sqlite")


@pytest.mark.parametrize(
    ("column", "expected_postgres", "expected_mysql"),
    [
        ({"name": "c", "type": "int"}, "BIGINT", "BIGINT"),
        ({"name": "c", "type": "float"}, "DOUBLE PRECISION", "DOUBLE"),
        ({"name": "c", "type": "boolean"}, "BOOLEAN", "BOOLEAN"),
        ({"name": "c", "type": "date"}, "DATE", "DATE"),
        ({"name": "c", "type": "time"}, "TIME", "TIME"),
        ({"name": "c", "type": "uuid"}, "UUID", "CHAR(36)"),
        ({"name": "c", "type": "json"}, "JSONB", "JSON"),
        ({"name": "c", "type": "text"}, "TEXT", "TEXT"),
        (
            {"name": "c", "type": "decimal", "params": {"precision": 5, "scale": 1}},
            "DECIMAL(5, 1)",
            "DECIMAL(5, 1)",
        ),
    ],
)
def test_mapeamento_de_tipos_ddl(
    column: dict[str, object], expected_postgres: str, expected_mysql: str
) -> None:
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
    assert expected_postgres in ddl_for(schema, "postgres")
    assert expected_mysql in ddl_for(schema, "mysql")


def test_timestamp_com_timezone() -> None:
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
                        {"name": "ts", "type": "timestamp", "params": {"timezone": True}},
                    ],
                }
            ],
        }
    )
    assert "TIMESTAMPTZ(3)" in ddl_for(schema, "postgres")
    assert "TIMESTAMP(3)" in ddl_for(schema, "mysql")


def test_array_postgres_usa_colchetes_e_mysql_usa_json() -> None:
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
    assert "VARCHAR(10)[]" in ddl_for(schema, "postgres")
    assert "JSON" in ddl_for(schema, "mysql")


def test_ciclo_de_referencias_gera_erro() -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "a",
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "rows_from": {
                        "via": "b_id",
                        "relation": "one_to_many",
                        "cardinality": {"range": {"min": 0, "max": 1}},
                    },
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "b_id", "type": "ref", "params": {"table": "b"}},
                    ],
                },
                {
                    "name": "b",
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "rows_from": {
                        "via": "a_id",
                        "relation": "one_to_many",
                        "cardinality": {"range": {"min": 0, "max": 1}},
                    },
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "a_id", "type": "ref", "params": {"table": "a"}},
                    ],
                },
            ],
        }
    )
    with pytest.raises(SchemaError):
        ddl_for(schema, "postgres")
