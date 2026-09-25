"""Testes de integração dos sinks de banco (DD-02, E.6, E.8: E-04, E-05, E-09) com
Postgres e MySQL reais via `testcontainers`. Exigem Docker e rede; não rodam no gate
rápido (`-m "not integration and not slow and not ray and not docker"`).
"""

from __future__ import annotations

import pyarrow as pa
import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("testcontainers")
pytest.importorskip("psycopg")
pytest.importorskip("pymysql")


@pytest.fixture(scope="module")
def postgres_dsn() -> str:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine") as container:
        yield container.get_connection_url().replace("postgresql+psycopg2", "postgresql")


def test_postgres_rewriting_the_same_chunk_does_not_duplicate_rows(
    postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-04: reexecutar o mesmo chunk não duplica linhas; COUNT(*) bate com o plano."""
    import psycopg

    monkeypatch.setenv("TEST_PG_DSN", postgres_dsn)

    from dataipsum.contracts.sink import RunContext
    from dataipsum.schema.models import ColumnSpec, PrimaryKeySpec, TableSpec
    from dataipsum.sinks.postgres_sink import PostgresSink

    with psycopg.connect(postgres_dsn) as connection, connection.cursor() as cursor:
        cursor.execute("CREATE TABLE usuarios (id BIGINT PRIMARY KEY, nome TEXT NOT NULL)")
    table = TableSpec(
        name="usuarios",
        rows=2,
        primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence", start=1),
        columns=[ColumnSpec(name="id", type="int64"), ColumnSpec(name="nome", type="string")],
    )
    schema = pa.schema([("id", pa.int64()), ("nome", pa.string())])
    batch = pa.record_batch([pa.array([1, 2]), pa.array(["Ana", "Bia"])], schema=schema)

    sink = PostgresSink({"dsn_env": "TEST_PG_DSN"})
    run = RunContext(run_id="run-1", out_dir="/tmp/out", seed=1)
    sink.open(run, table, schema)
    sink.write_chunk(1, batch)
    sink.write_chunk(1, batch)
    sink.close()

    with psycopg.connect(postgres_dsn) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM usuarios")
        assert cursor.fetchone()[0] == 2
