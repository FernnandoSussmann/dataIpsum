"""Conexão/cursor fake para testar a sequência transacional dos sinks de banco
(DD-02, E.6) sem precisar de `psycopg`/`PyMySQL` instalados nem de rede."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass
class FakeCopy:
    rows: list[tuple[object, ...]] = field(default_factory=list)

    def __enter__(self) -> FakeCopy:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def write_row(self, row: Sequence[object]) -> None:
        self.rows.append(tuple(row))


@dataclass
class FakeCursor:
    control_status_queue: list[str | None] = field(default_factory=list)
    executed: list[tuple[str, object]] = field(default_factory=list)
    executed_many: list[tuple[str, list[object]]] = field(default_factory=list)
    copies: list[FakeCopy] = field(default_factory=list)
    raise_on_execute: Exception | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        if self.raise_on_execute is not None:
            raise self.raise_on_execute
        self.executed.append((sql, params))

    def executemany(self, sql: str, params_list: list[object]) -> None:
        self.executed_many.append((sql, params_list))

    def fetchone(self) -> tuple[str] | None:
        if not self.control_status_queue:
            return None
        status = self.control_status_queue.pop(0)
        return None if status is None else (status,)

    def copy(self, sql: str) -> FakeCopy:
        fake_copy = FakeCopy()
        self.copies.append(fake_copy)
        self.executed.append((sql, None))
        return fake_copy


@dataclass
class FakeConnection:
    cursor_obj: FakeCursor = field(default_factory=FakeCursor)
    committed: int = 0
    rolled_back: int = 0
    autocommit: bool = False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        return None
