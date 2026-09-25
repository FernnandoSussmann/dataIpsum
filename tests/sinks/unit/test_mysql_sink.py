"""Testes do sink `mysql` (DD-02, E.3.2, E.6): sequência transacional testada com
uma conexão/cursor fake, sem `PyMySQL` nem rede."""

from __future__ import annotations

import pyarrow as pa
import pytest
from tests.sinks._db_fakes import FakeConnection, FakeCursor
from tests.sinks.conftest import make_column, make_run_context, make_table

from dataipsum.errors import SinkError
from dataipsum.sinks.mysql_sink import MysqlSink


def _sink_with_fake_connection(columns: list, fake_connection: FakeConnection) -> tuple:
    table = make_table("usuarios", columns)
    run = make_run_context("/out")
    sink = MysqlSink()
    sink._table = table  # noqa: SLF001
    sink._run = run  # noqa: SLF001
    sink._connection = fake_connection  # noqa: SLF001
    return sink, table


def test_capabilities_referential_integrity_true() -> None:
    assert MysqlSink.capabilities.referential_integrity is True


def test_new_chunk_inserts_rows_and_commits() -> None:
    fake_connection = FakeConnection(cursor_obj=FakeCursor(control_status_queue=[None]))
    sink, _table = _sink_with_fake_connection([make_column("id", "int64")], fake_connection)
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1, 2])], schema=schema)

    receipt = sink.write_chunk(1, batch)

    cursor = fake_connection.cursor_obj
    insert_calls = [sql for sql, _ in cursor.executed_many if sql.startswith("INSERT INTO")]
    assert len(insert_calls) == 1
    assert fake_connection.committed == 1
    assert receipt.sink_ref.startswith("mysql://")


def test_idempotent_when_already_committed() -> None:
    fake_connection = FakeConnection(cursor_obj=FakeCursor(control_status_queue=["committed"]))
    sink, _table = _sink_with_fake_connection([make_column("id", "int64")], fake_connection)
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1])], schema=schema)

    sink.write_chunk(1, batch)

    assert fake_connection.cursor_obj.executed_many == []
    assert fake_connection.committed == 1


def test_placeholder_replacement_uses_update_not_delete() -> None:
    columns = [
        make_column("id", "int64"),
        make_column("comentario", "llm_post"),
        make_column("is_offensive", "boolean"),
        make_column("is_placeholder", "boolean"),
    ]
    fake_connection = FakeConnection(cursor_obj=FakeCursor(control_status_queue=["placeholder"]))
    sink, _table = _sink_with_fake_connection(columns, fake_connection)
    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("comentario", pa.string()),
            ("is_offensive", pa.bool_()),
            ("is_placeholder", pa.bool_()),
        ]
    )
    batch = pa.record_batch(
        [pa.array([1]), pa.array(["texto"]), pa.array([False]), pa.array([False])], schema=schema
    )

    sink.write_chunk(1, batch)

    cursor = fake_connection.cursor_obj
    update_calls = [sql for sql, _ in cursor.executed_many if sql.startswith("UPDATE")]
    assert len(update_calls) == 1
    assert all("DELETE" not in sql for sql, _ in cursor.executed_many)


def test_error_rolls_back_and_raises_sink_error() -> None:
    fake_connection = FakeConnection(
        cursor_obj=FakeCursor(control_status_queue=[None], raise_on_execute=RuntimeError("boom"))
    )
    sink, _table = _sink_with_fake_connection([make_column("id", "int64")], fake_connection)
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1])], schema=schema)

    with pytest.raises(SinkError):
        sink.write_chunk(1, batch)

    assert fake_connection.rolled_back == 1


def test_local_infile_disabled_and_no_dsn_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    calls: list[dict[str, object]] = []

    class _FakeConnection:
        def close(self) -> None:
            return None

    def _fake_connect(**kwargs: object) -> _FakeConnection:
        calls.append(kwargs)
        return _FakeConnection()

    fake_module = types.ModuleType("pymysql")
    fake_module.connect = _fake_connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pymysql", fake_module)
    monkeypatch.setenv("MYSQL_PASS", "SEGREDO456")

    from dataipsum.sinks.mysql_sink import _connect

    _connect({"host": "db", "password_env": "MYSQL_PASS"})

    assert len(calls) == 1
    assert calls[0]["local_infile"] is False
    assert calls[0]["autocommit"] is False
