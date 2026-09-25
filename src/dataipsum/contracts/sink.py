"""Contrato `Sink` (DD-00 §3.5). Implementações concretas vivem na trilha E (DD-02)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

import pyarrow as pa

if TYPE_CHECKING:
    from dataipsum.schema.models import Schema

ChunkState = Literal["absent", "committed"]


@dataclass(frozen=True)
class RunContext:
    run_id: str
    out_dir: str
    seed: int
    schema: Schema | None = None
    """Schema completo da execução (DD-02 §0, seam E↔F).

    Sinks recebem só a própria `TableSpec` em `open()`; `ddl_for`/`avro_schema`
    (trilha F) precisam do `Schema` inteiro para resolver colunas `ref` contra a
    tabela referenciada. `None` quando o chamador não tem o schema disponível
    (ex.: testes que não exercitam `create_tables`/Kafka) — nesse caso, os sinks
    que precisam dele levantam `SinkError` com uma mensagem clara em vez de falhar
    com um erro de atributo/tipo obscuro.
    """


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
