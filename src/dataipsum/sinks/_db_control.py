"""Helpers compartilhados pelos sinks de banco (`postgres`, `mysql`), DD-02 E.3.2:
tabela de controle `_dataipsum_chunks`, resolução de opções de conexão e detecção
das colunas LLM/flags usadas na substituição de chunks `placeholder`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dataipsum.errors import SinkError
from dataipsum.schema.models import IDENTIFIER_PATTERN, TableSpec

CONTROL_TABLE_NAME = "_dataipsum_chunks"

FLAG_COLUMN_NAMES = frozenset({"is_offensive", "is_placeholder"})

DEFAULT_DB_SCHEMA = "public"
DEFAULT_SSLMODE = "prefer"
UPDATE_BATCH_SIZE = 1000


def llm_and_flag_column_names(table: TableSpec) -> tuple[str, ...]:
    """Colunas atualizadas na substituição de um chunk `placeholder` (E.3.2): as
    colunas `llm_*` e as flags `is_offensive`/`is_placeholder`."""
    return tuple(
        column.name for column in table.columns if column.is_llm or column.name in FLAG_COLUMN_NAMES
    )


@dataclass(frozen=True)
class ConnectionOptions:
    dsn: str | None
    host: str | None
    port: int | None
    database: str | None
    user: str | None
    password: str | None
    sslmode: str


def resolve_connection_options(options: Mapping[str, object]) -> ConnectionOptions:
    """DSN por `dsn_env`, ou host/port/database/user + `password_env` (E.3.2).
    Segredos só entram por `*_env`: o valor nunca vem de uma chave em texto claro."""
    dsn = _read_env_option(options, "dsn_env")
    password = _read_env_option(options, "password_env")
    port_value = options.get("port")
    return ConnectionOptions(
        dsn=dsn,
        host=_optional_str(options.get("host")),
        port=int(str(port_value)) if port_value is not None else None,
        database=_optional_str(options.get("database")),
        user=_optional_str(options.get("user")),
        password=password,
        sslmode=str(options.get("sslmode", DEFAULT_SSLMODE)),
    )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _read_env_option(options: Mapping[str, object], option_key: str) -> str | None:
    env_var_name = options.get(option_key)
    if env_var_name is None:
        return None
    value = os.environ.get(str(env_var_name))
    if not value:
        raise SinkError(
            f"variável de ambiente '{env_var_name}' (opção '{option_key}') não definida ou vazia"
        )
    return value


def primary_key_values(table: TableSpec, row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(row[name] for name in table.primary_key.columns)


def batched(items: Sequence[object], size: int) -> list[list[object]]:
    return [list(items[start : start + size]) for start in range(0, len(items), size)]


def validated_table(table: object) -> TableSpec:
    if not isinstance(table, TableSpec):
        raise SinkError(f"esperado TableSpec, recebido {type(table).__name__}")
    if not IDENTIFIER_PATTERN.fullmatch(table.name):
        raise SinkError(f"nome de tabela inválido para sink de banco: '{table.name}'")
    return table


def quote_identifier_backtick(name: str) -> str:
    """Quota um identificador MySQL com crase, escapando crases internas (E.5.3)."""
    return "`" + name.replace("`", "``") + "`"
