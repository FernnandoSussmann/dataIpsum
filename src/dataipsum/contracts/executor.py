"""Contrato `Executor`, `ChunkTask`/`ChunkResult` e `LLMLimiter` (DD-00 §3.5)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

from dataipsum.contracts.planner import ChunkSpec

if TYPE_CHECKING:
    from dataipsum.schema.models import Schema

ChunkStatus = Literal["done", "pending", "pending_llm", "failed"]


@dataclass(frozen=True)
class BlockedBy:
    table: str
    chunk_id: int


@dataclass(frozen=True)
class ChunkTask:
    """Unidade de trabalho do executor. Autocontida e picklable, sem estado compartilhado."""

    table: str
    chunk_spec: ChunkSpec
    schema: Schema
    root_seed: int
    sink_options: dict[str, object]
    run_options: dict[str, object]


@dataclass(frozen=True)
class ChunkResultFlags:
    placeholders: int = 0
    offensive: int = 0
    toxicity_exhausted: int = 0
    thread_fallbacks: int = 0


@dataclass(frozen=True)
class ChunkResult:
    table: str
    chunk_id: int
    status: ChunkStatus
    rows: int
    sink_ref: str | None = None
    sha256: str | None = None
    flags: ChunkResultFlags = field(default_factory=ChunkResultFlags)
    blocked_by: tuple[BlockedBy, ...] = field(default_factory=tuple)
    error: str | None = None


class LLMLimiter(Protocol):
    """Semáforo entre processos/nós que limita chamadas LLM por provedor."""

    def __enter__(self) -> LLMLimiter: ...

    def __exit__(self, *exc_info: object) -> None: ...


class Executor(Protocol):
    def submit(self, tasks: Iterable[ChunkTask]) -> Iterator[ChunkResult]:
        """Resultados fora de ordem."""
        ...

    def set_concurrency(self, n: int) -> None: ...

    @property
    def concurrency(self) -> int: ...

    def shutdown(self, wait: bool) -> None: ...

    def llm_limiter(self, provider_name: str, max_concurrency: int) -> LLMLimiter: ...
