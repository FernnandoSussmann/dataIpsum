"""Sink `mysql` (DD-02, trilha E, M3, E.3.2): `INSERT` em lotes + tabela de controle
transacional. Exige o extra opcional `mysql` (`PyMySQL`); só é registrado por
`sinks.register` quando esse pacote está instalável (E.4).

`local_infile` fica sempre desligado (E.5.3): a carga usa `INSERT ... VALUES` via
`executemany`, nunca `LOAD DATA`. Identificadores são pré-validados pela regex do
DD-00 (§6) e sempre quotados com crase, com escape de crases internas.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar, cast
from urllib.parse import urlparse

import pyarrow as pa

from dataipsum.contracts.sink import ChunkState, RunContext, SinkCapabilities, SinkReceipt
from dataipsum.errors import SinkError
from dataipsum.schema.models import TableSpec
from dataipsum.sinks._db_control import (
    CONTROL_TABLE_NAME,
    UPDATE_BATCH_SIZE,
    batched,
    llm_and_flag_column_names,
    primary_key_values,
    quote_identifier_backtick,
    resolve_connection_options,
    validated_table,
)
from dataipsum.sinks.schema_stubs import load_ddl_for, require_schema

if TYPE_CHECKING:
    from dataipsum.schema.models import Schema

DIALECT = "mysql"
INSERT_BATCH_SIZE = 1000


def _qualified(table_name: str) -> str:
    return quote_identifier_backtick(table_name)


def _connect(options: Mapping[str, object]) -> Any:
    connection_options = resolve_connection_options(options)

    import pymysql

    host, port, database, user = (
        connection_options.host,
        connection_options.port,
        connection_options.database,
        connection_options.user,
    )
    if connection_options.dsn is not None:
        parsed = urlparse(connection_options.dsn)
        host = parsed.hostname or host
        port = parsed.port or port
        database = (parsed.path.lstrip("/") or database) if parsed.path else database
        user = parsed.username or user
    ssl_options: dict[str, object] = (
        {"ssl": {}} if connection_options.sslmode not in ("disable", "") else {}
    )
    return pymysql.connect(
        host=host,
        port=port or 3306,
        db=database,
        user=user,
        password=connection_options.password or "",
        autocommit=False,
        local_infile=False,
        **ssl_options,
    )


def _ensure_control_table(cursor: Any) -> None:
    cursor.execute(
        f"CREATE TABLE IF NOT EXISTS {_qualified(CONTROL_TABLE_NAME)} ("
        "run_id VARCHAR(64) NOT NULL, table_name VARCHAR(63) NOT NULL, "
        "chunk_id INT NOT NULL, status VARCHAR(16) NOT NULL, rows INT NOT NULL, "
        "committed_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3), "
        "PRIMARY KEY (run_id, table_name, chunk_id)) ENGINE=InnoDB"
    )


def _create_tables_if_missing(cursor: Any, schema: Schema) -> None:
    """`create_tables` (E.3.2): executa o DDL do schema inteiro (`ddl_for`, trilha
    F), com `CREATE TABLE IF NOT EXISTS` em cada tabela — não só a desta sink,
    porque `ddl_for` precisa do schema inteiro para resolver as FKs (`ref`), e a
    ordem topológica que ele já aplica garante que tabelas-pai venham primeiro."""
    ddl_for = load_ddl_for()
    for statement in ddl_for(schema, DIALECT).strip().split(";\n"):
        if statement.strip():
            cursor.execute(statement.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1))


def select_control_status(cursor: Any, run_id: str, table_name: str, chunk_id: int) -> str | None:
    cursor.execute(
        # Identificador fixo (CONTROL_TABLE_NAME); valores sempre por parâmetros (E.5.3).
        f"SELECT status FROM {_qualified(CONTROL_TABLE_NAME)} "  # nosec B608
        "WHERE run_id = %s AND table_name = %s AND chunk_id = %s",
        (run_id, table_name, chunk_id),
    )
    row = cursor.fetchone()
    return None if row is None else cast(str, row[0])


def _upsert_control_row(
    cursor: Any, run_id: str, table_name: str, chunk_id: int, rows: int
) -> None:
    cursor.execute(
        # Identificador fixo (CONTROL_TABLE_NAME); valores sempre por parâmetros (E.5.3).
        f"INSERT INTO {_qualified(CONTROL_TABLE_NAME)} "  # nosec B608
        "(run_id, table_name, chunk_id, status, rows, committed_at) "
        "VALUES (%s, %s, %s, 'committed', %s, NOW(3)) "
        "ON DUPLICATE KEY UPDATE status = 'committed', rows = VALUES(rows), "
        "committed_at = NOW(3)",
        (run_id, table_name, chunk_id, rows),
    )


def _insert_rows(cursor: Any, table: TableSpec, batch: pa.RecordBatch) -> None:
    column_names = batch.schema.names
    columns_sql = ", ".join(quote_identifier_backtick(name) for name in column_names)
    placeholders = ", ".join(["%s"] * len(column_names))
    # `table.name` já foi validado pela regex de identificador do DD-00 (E.5.3); valores
    # sempre por parâmetros.
    statement = f"INSERT INTO {_qualified(table.name)} ({columns_sql}) VALUES ({placeholders})"  # nosec B608
    rows = [tuple(row[name] for name in column_names) for row in batch.to_pylist()]
    for batch_of_rows in batched(rows, INSERT_BATCH_SIZE):
        cursor.executemany(statement, batch_of_rows)


def _replace_placeholder_rows(cursor: Any, table: TableSpec, batch: pa.RecordBatch) -> None:
    update_columns = llm_and_flag_column_names(table)
    if not update_columns:
        return
    set_clause = ", ".join(f"{quote_identifier_backtick(name)} = %s" for name in update_columns)
    where_clause = " AND ".join(
        f"{quote_identifier_backtick(name)} = %s" for name in table.primary_key.columns
    )
    # `table.name` e as colunas já vêm quotadas/validadas acima; valores por parâmetros.
    statement = f"UPDATE {_qualified(table.name)} SET {set_clause} WHERE {where_clause}"  # nosec B608
    rows = batch.to_pylist()
    parameters = [
        tuple(row[name] for name in update_columns) + primary_key_values(table, row) for row in rows
    ]
    for batch_of_params in batched(parameters, UPDATE_BATCH_SIZE):
        cursor.executemany(statement, batch_of_params)


class MysqlSink:
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
        with self._connection.cursor() as cursor:
            _ensure_control_table(cursor)
            if bool(self.options.get("create_tables", False)):
                _create_tables_if_missing(cursor, require_schema(run))
        self._connection.commit()

    def write_chunk(self, chunk_id: int, batch: pa.RecordBatch | object) -> SinkReceipt:
        connection = self._require_connection()
        table = self._require_table()
        run = self._require_run()
        record_batch = cast(pa.RecordBatch, batch)
        try:
            with connection.cursor() as cursor:
                existing_status = select_control_status(cursor, run.run_id, table.name, chunk_id)
                if existing_status != "committed":
                    if existing_status == "placeholder":
                        _replace_placeholder_rows(cursor, table, record_batch)
                    else:
                        _insert_rows(cursor, table, record_batch)
                    _upsert_control_row(
                        cursor, run.run_id, table.name, chunk_id, record_batch.num_rows
                    )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise SinkError(
                f"falha ao gravar chunk {chunk_id} de '{table.name}' no MySQL: {exc}"
            ) from exc
        return SinkReceipt(sink_ref=f"mysql://{table.name}/{chunk_id}")

    def chunk_state(self, chunk_id: int) -> ChunkState:
        connection = self._require_connection()
        table = self._require_table()
        run = self._require_run()
        with connection.cursor() as cursor:
            status = select_control_status(cursor, run.run_id, table.name, chunk_id)
        return "committed" if status == "committed" else "absent"

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

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
