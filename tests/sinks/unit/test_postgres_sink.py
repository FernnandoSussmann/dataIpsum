"""Testes do sink `postgres` (DD-02, E.3.2, E.6): sequência transacional testada com
uma conexão/cursor fake, sem `psycopg` nem rede."""

from __future__ import annotations

import pyarrow as pa
import pytest
from tests.sinks._db_fakes import FakeConnection, FakeCursor
from tests.sinks.conftest import make_column, make_run_context, make_table

from dataipsum.errors import SinkError
from dataipsum.sinks.postgres_sink import PostgresSink


def _sink_with_fake_connection(table_columns: list, fake_connection: FakeConnection) -> tuple:
    table = make_table("usuarios", table_columns)
    run = make_run_context("/out")
    sink = PostgresSink()
    sink._table = table  # noqa: SLF001 -- bypass open()/_connect() propositalmente (sem psycopg)
    sink._run = run  # noqa: SLF001
    sink._connection = fake_connection  # noqa: SLF001
    return sink, table


def test_capabilities_referential_integrity_true() -> None:
    assert PostgresSink.capabilities.referential_integrity is True
    assert PostgresSink.capabilities.atomic_chunk is True
    assert PostgresSink.capabilities.replace_chunk is True


def test_new_chunk_uses_copy_then_upserts_control_and_commits() -> None:
    fake_connection = FakeConnection(cursor_obj=FakeCursor(control_status_queue=[None]))
    sink, table = _sink_with_fake_connection([make_column("id", "int64")], fake_connection)
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1, 2, 3])], schema=schema)

    receipt = sink.write_chunk(1, batch)

    cursor = fake_connection.cursor_obj
    assert len(cursor.copies) == 1
    assert cursor.copies[0].rows == [(1,), (2,), (3,)]
    control_statements = [sql for sql, _ in cursor.executed if "_dataipsum_chunks" in sql]
    assert any("SELECT status" in sql for sql in control_statements)
    assert any("INSERT INTO" in sql for sql in control_statements)
    assert fake_connection.committed == 1
    assert fake_connection.rolled_back == 0
    assert receipt.sink_ref.startswith("postgres://")


def test_already_committed_chunk_is_idempotent_and_skips_copy() -> None:
    fake_connection = FakeConnection(cursor_obj=FakeCursor(control_status_queue=["committed"]))
    sink, _table = _sink_with_fake_connection([make_column("id", "int64")], fake_connection)
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1])], schema=schema)

    sink.write_chunk(1, batch)

    assert fake_connection.cursor_obj.copies == []
    assert fake_connection.committed == 1


def test_placeholder_replacement_updates_llm_and_flag_columns_only() -> None:
    columns = [
        make_column("id", "int64"),
        make_column("comentario", "llm_post"),
        make_column("is_offensive", "boolean"),
        make_column("is_placeholder", "boolean"),
    ]
    fake_connection = FakeConnection(cursor_obj=FakeCursor(control_status_queue=["placeholder"]))
    sink, table = _sink_with_fake_connection(columns, fake_connection)
    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("comentario", pa.string()),
            ("is_offensive", pa.bool_()),
            ("is_placeholder", pa.bool_()),
        ]
    )
    batch = pa.record_batch(
        [pa.array([1]), pa.array(["texto real"]), pa.array([False]), pa.array([False])],
        schema=schema,
    )

    sink.write_chunk(1, batch)

    cursor = fake_connection.cursor_obj
    assert cursor.copies == []
    update_calls = [sql for sql, _ in cursor.executed_many]
    assert len(update_calls) == 1
    update_sql = update_calls[0]
    assert update_sql.startswith("UPDATE")
    assert "DELETE" not in update_sql
    assert '"comentario"' in update_sql
    assert '"is_offensive"' in update_sql
    assert '"is_placeholder"' in update_sql
    assert '"id"' not in update_sql.split("SET")[1].split("WHERE")[0]
    _, params_list = cursor.executed_many[0]
    assert params_list == [("texto real", False, False, 1)]


def test_error_during_write_rolls_back_and_raises_sink_error() -> None:
    fake_connection = FakeConnection(
        cursor_obj=FakeCursor(
            control_status_queue=[None], raise_on_execute=RuntimeError("disco cheio")
        )
    )
    sink, _table = _sink_with_fake_connection([make_column("id", "int64")], fake_connection)
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1])], schema=schema)

    with pytest.raises(SinkError):
        sink.write_chunk(1, batch)

    assert fake_connection.rolled_back == 1
    assert fake_connection.committed == 0


def test_chunk_state_reflects_control_table() -> None:
    fake_connection = FakeConnection(cursor_obj=FakeCursor(control_status_queue=["committed"]))
    sink, _table = _sink_with_fake_connection([make_column("id", "int64")], fake_connection)

    assert sink.chunk_state(1) == "committed"


def test_chunk_state_absent_when_no_control_row() -> None:
    fake_connection = FakeConnection(cursor_obj=FakeCursor(control_status_queue=[None]))
    sink, _table = _sink_with_fake_connection([make_column("id", "int64")], fake_connection)

    assert sink.chunk_state(1) == "absent"


def test_dsn_env_missing_raises_without_leaking_variable_name_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PG_DSN", raising=False)
    sink = PostgresSink({"dsn_env": "PG_DSN"})
    table = make_table("t", [make_column("id", "int64")])
    schema = pa.schema([("id", pa.int64())])
    with pytest.raises(SinkError) as exc_info:
        sink.open(make_run_context("/out"), table, schema)
    assert "PG_DSN" in str(exc_info.value)


def test_password_env_value_never_appears_in_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_PASS", "SEGREDO123")
    fake_connection = FakeConnection(
        cursor_obj=FakeCursor(control_status_queue=[None], raise_on_execute=RuntimeError("boom"))
    )
    sink = PostgresSink({"password_env": "PG_PASS"})
    sink._table = make_table("t", [make_column("id", "int64")])  # noqa: SLF001
    sink._run = make_run_context("/out")  # noqa: SLF001
    sink._connection = fake_connection  # noqa: SLF001
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1])], schema=schema)

    with pytest.raises(SinkError) as exc_info:
        sink.write_chunk(1, batch)

    assert "SEGREDO123" not in str(exc_info.value)
