"""Integração real de `ddl_for`/`import_ddl` com Postgres e MySQL (DD-02 §F-01, §F.6).

Marcados `integration`: exigem Docker (via `testcontainers`) e não rodam no job de testes
rápidos. Cobrem o critério F-01 ("o DDL exportado executa sem erro em Postgres 16 e MySQL 8")
e a leitura de volta via `information_schema` para o import (não testado aqui: `import_ddl`
não abre conexões por design — a leitura real do catálogo pertence à trilha E quando ela
consumir `ddl_for`/`create_tables`).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlglot

from dataipsum.schema.models import Schema
from dataipsum.schema_io import ddl_for

pytestmark = pytest.mark.integration


@pytest.fixture
def loja_schema() -> Schema:
    return Schema.model_validate(
        {
            "version": 1,
            "name": "loja",
            "tables": [
                {
                    "name": "usuarios",
                    "rows": 10,
                    "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "nome", "type": "nome_proprio", "max_length": 120},
                        {"name": "cpf", "type": "cpf", "format": "masked"},
                        {"name": "bio", "type": "string", "max_length": 200, "null_ratio": 0.1},
                        {"name": "criado_em", "type": "timestamp"},
                    ],
                },
                {
                    "name": "pedidos",
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "rows_from": {
                        "via": "usuario_id",
                        "relation": "one_to_many",
                        "cardinality": {"range": {"min": 0, "max": 5}},
                    },
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                    ],
                },
            ],
        }
    )


@pytest.fixture
def postgres_connection(loja_schema: Schema) -> Iterator[object]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16") as container:
        import psycopg

        with psycopg.connect(container.get_connection_url().replace("+psycopg2", "")) as conn:
            yield conn


@pytest.fixture
def mysql_connection(loja_schema: Schema) -> Iterator[object]:
    from testcontainers.mysql import MySqlContainer

    with MySqlContainer("mysql:8") as container:
        import pymysql

        with pymysql.connect(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(3306)),
            user=container.username,
            password=container.password,
            database=container.dbname,
        ) as conn:
            yield conn


def test_ddl_postgres_executa_sem_erro(loja_schema: Schema, postgres_connection: object) -> None:
    sql = ddl_for(loja_schema, "postgres")
    with postgres_connection.cursor() as cursor:  # type: ignore[attr-defined]
        for statement in sqlglot.parse(sql, read="postgres"):
            cursor.execute(statement.sql(dialect="postgres"))  # type: ignore[union-attr]
    postgres_connection.commit()  # type: ignore[attr-defined]


def test_ddl_mysql_executa_sem_erro(loja_schema: Schema, mysql_connection: object) -> None:
    sql = ddl_for(loja_schema, "mysql")
    with mysql_connection.cursor() as cursor:  # type: ignore[attr-defined]
        for statement in sqlglot.parse(sql, read="mysql"):
            cursor.execute(statement.sql(dialect="mysql"))  # type: ignore[union-attr]
    mysql_connection.commit()  # type: ignore[attr-defined]
