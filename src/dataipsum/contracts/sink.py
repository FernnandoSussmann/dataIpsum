"""Contrato `Sink` (DD-00 §3.5). Implementações concretas vivem na trilha E (DD-02)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import pyarrow as pa

ChunkState = Literal["absent", "committed"]


@dataclass(frozen=True)
class RunContext:
    run_id: str
    out_dir: str
    seed: int


@dataclass(frozen=True)
class SinkCapabilities:
    atomic_chunk: bool
    replace_chunk: bool
    referential_integrity: bool


@dataclass(frozen=True)
class SinkReceipt:
    sink_ref: str
    sha256: str | None = None


class Sink(Protocol):
    capabilities: SinkCapabilities

    def open(self, run: RunContext, table: object, arrow_schema: pa.Schema) -> None: ...

    def write_chunk(self, chunk_id: int, batch: pa.RecordBatch | object) -> SinkReceipt:
        """Idempotente: reescrever o mesmo chunk_id substitui atomicamente."""
        ...

    def chunk_state(self, chunk_id: int) -> ChunkState: ...

    def close(self) -> None: ...
