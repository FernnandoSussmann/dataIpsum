"""Sink `postgres` (DD-02, trilha E, M3, E.3.2): `COPY` + tabela de controle
transacional. Exige o extra opcional `postgres` (`psycopg[binary]`); só é
registrado por `sinks.register` quando esse pacote está instalável (E.4).

Identificadores (nomes de schema/tabela/coluna) são sempre pré-validados pela
regex de identificador do DD-00 (§6) antes de entrar em qualquer SQL, e sempre
quotados (aspas duplas, com escape de aspas internas) — nunca concatenados como
valor bruto (E.5.3). A conexão real (`psycopg.connect`) é resolvida só dentro de
`_connect`, para que a lógica de transação seja testável com uma conexão/cursor
fake, sem exigir o pacote `psycopg` instalado.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, cast

import pyarrow as pa

from dataipsum.contracts.sink import ChunkState, RunContext, SinkCapabilities, SinkReceipt
from dataipsum.errors import SinkError
from dataipsum.schema.models import TableSpec
from dataipsum.sinks._db_control import (
    CONTROL_TABLE_NAME,
    DEFAULT_DB_SCHEMA,
    UPDATE_BATCH_SIZE,
    batched,
    llm_and_flag_column_names,
    primary_key_values,
    resolve_connection_options,
    validated_table,
)
from dataipsum.sinks.schema_stubs import load_ddl_for

DIALECT = "postgres"


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _qualified(db_schema: str, table_name: str) -> str:
    return f"{_quote_ident(db_schema)}.{_quote_ident(table_name)}"


def _connect(options: Mapping[str, object]) -> Any:
    connection_options = resolve_connection_options(options)

    import psycopg  # type: ignore[import-not-found]

    if connection_options.dsn is not None:
        connection = psycopg.connect(connection_options.dsn, sslmode=connection_options.sslmode)
    else:
        connection = psycopg.connect(
            host=connection_options.host,
            port=connection_options.port,
            dbname=connection_options.database,
            user=connection_options.user,
            password=connection_options.password,
            sslmode=connection_options.sslmode,
        )
    connection.autocommit = False
    return connection


def _ensure_control_table(cursor: Any, db_schema: str) -> None:
    cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(db_schema)}")
    cursor.execute(
        f"CREATE TABLE IF NOT EXISTS {_qualified(db_schema, CONTROL_TABLE_NAME)} ("
        "run_id text NOT NULL, table_name text NOT NULL, chunk_id integer NOT NULL, "
        "status text NOT NULL, rows integer NOT NULL, "
        "committed_at timestamptz NOT NULL DEFAULT now(), "
        "PRIMARY KEY (run_id, table_name, chunk_id))"
    )


def _create_table_if_missing(cursor: Any, table: TableSpec) -> None:
    ddl_for = load_ddl_for()
    cursor.execute(ddl_for(table, DIALECT))


def select_control_status(
    cursor: Any, db_schema: str, run_id: str, table_name: str, chunk_id: int
) -> str | None:
    cursor.execute(
        f"SELECT status FROM {_qualified(db_schema, CONTROL_TABLE_NAME)} "
        "WHERE run_id = %s AND table_name = %s AND chunk_id = %s",
        (run_id, table_name, chunk_id),
    )
    row = cursor.fetchone()
    return None if row is None else cast(str, row[0])


def _upsert_control_row(
    cursor: Any, db_schema: str, run_id: str, table_name: str, chunk_id: int, rows: int
) -> None:
    qualified = _qualified(db_schema, CONTROL_TABLE_NAME)
    cursor.execute(
        f"INSERT INTO {qualified} (run_id, table_name, chunk_id, status, rows, committed_at) "
        "VALUES (%s, %s, %s, 'committed', %s, now()) "
        "ON CONFLICT (run_id, table_name, chunk_id) "
        "DO UPDATE SET status = 'committed', rows = EXCLUDED.rows, committed_at = now()",
        (run_id, table_name, chunk_id, rows),
    )


def _copy_rows(cursor: Any, db_schema: str, table: TableSpec, batch: pa.RecordBatch) -> None:
    column_names = batch.schema.names
    columns_sql = ", ".join(_quote_ident(name) for name in column_names)
    qualified = _qualified(db_schema, table.name)
    with cursor.copy(f"COPY {qualified} ({columns_sql}) FROM STDIN") as copy:
        for row in batch.to_pylist():
            copy.write_row(tuple(row[name] for name in column_names))


def _replace_placeholder_rows(
    cursor: Any, db_schema: str, table: TableSpec, batch: pa.RecordBatch
) -> None:
    update_columns = llm_and_flag_column_names(table)
    if not update_columns:
        return
    qualified = _qualified(db_schema, table.name)
    set_clause = ", ".join(f"{_quote_ident(name)} = %s" for name in update_columns)
    where_clause = " AND ".join(f"{_quote_ident(name)} = %s" for name in table.primary_key.columns)
    statement = f"UPDATE {qualified} SET {set_clause} WHERE {where_clause}"
    rows = batch.to_pylist()
    parameters = [
        tuple(row[name] for name in update_columns) + primary_key_values(table, row) for row in rows
    ]
    for batch_of_params in batched(parameters, UPDATE_BATCH_SIZE):
        cursor.executemany(statement, batch_of_params)


class PostgresSink:
    capabilities: ClassVar[SinkCapabilities] = SinkCapabilities(
        atomic_chunk=True, replace_chunk=True, referential_integrity=True
    )

    def __init__(self, options: Mapping[str, object] | None = None) -> None:
        self.options: Mapping[str, object] = dict(options or {})
        self._connection: Any = None
        self._run: RunContext | None = None
        self._table: TableSpec | None = None

    def open(self, run: RunContext, table: object, arrow_schema: pa.Schema) -> None:
        self._table = validated_table(table)
        self._run = run
        self._connection = _connect(self.options)
        db_schema = self._db_schema()
        with self._connection.cursor() as cursor:
            _ensure_control_table(cursor, db_schema)
            if bool(self.options.get("create_tables", False)):
                _create_table_if_missing(cursor, self._table)
        self._connection.commit()

    def write_chunk(self, chunk_id: int, batch: pa.RecordBatch | object) -> SinkReceipt:
        connection = self._require_connection()
        table = self._require_table()
        run = self._require_run()
        record_batch = cast(pa.RecordBatch, batch)
        db_schema = self._db_schema()
        try:
            with connection.cursor() as cursor:
                existing_status = select_control_status(
                    cursor, db_schema, run.run_id, table.name, chunk_id
                )
                if existing_status != "committed":
                    if existing_status == "placeholder":
                        _replace_placeholder_rows(cursor, db_schema, table, record_batch)
                    else:
                        _copy_rows(cursor, db_schema, table, record_batch)
                    _upsert_control_row(
                        cursor, db_schema, run.run_id, table.name, chunk_id, record_batch.num_rows
                    )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise SinkError(
                f"falha ao gravar chunk {chunk_id} de '{table.name}' no Postgres: {exc}"
            ) from exc
        return SinkReceipt(sink_ref=f"postgres://{db_schema}.{table.name}/{chunk_id}")

    def chunk_state(self, chunk_id: int) -> ChunkState:
        connection = self._require_connection()
        table = self._require_table()
        run = self._require_run()
        with connection.cursor() as cursor:
            status = select_control_status(
                cursor, self._db_schema(), run.run_id, table.name, chunk_id
            )
        return "committed" if status == "committed" else "absent"

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _db_schema(self) -> str:
        return str(self.options.get("db_schema", DEFAULT_DB_SCHEMA))

    def _require_connection(self) -> Any:
        if self._connection is None:
            raise SinkError("sink não foi aberto: chame open() antes de write_chunk/chunk_state")
        return self._connection

    def _require_table(self) -> TableSpec:
        if self._table is None:
            raise SinkError("sink não foi aberto: chame open() antes de write_chunk/chunk_state")
        return self._table

    def _require_run(self) -> RunContext:
        if self._run is None:
            raise SinkError("sink não foi aberto: chame open() antes de write_chunk/chunk_state")
        return self._run
