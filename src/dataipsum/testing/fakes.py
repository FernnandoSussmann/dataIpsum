"""Fakes de teste (`dataipsum.testing`, DD-00 §3.11).

Cada fake implementa o `Protocol` correspondente em `dataipsum.contracts` de
forma mínima, para que uma trilha teste seu próprio código sem depender das
outras. `SchemaBuilder` é a exceção: `dataipsum.schema.models.Schema` ainda
não existe neste worktree (S4 roda em paralelo com S2), então ele produz um
`dict` no formato do §3.3 em vez de um `Schema` de verdade. Esse `dict` é um
`source` válido para `dataipsum.schema.loader.load_schema`/
`dataipsum.api.load_schema` (que aceitam `Path | str | dict`), então nada
precisa mudar em `SchemaBuilder` depois do merge do S2 — só passa a ser
possível encadear `.build()` num `load_schema` de verdade.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from dataipsum.contracts.executor import ChunkResult, ChunkTask
from dataipsum.contracts.llm import LLMRequest, LLMResponse
from dataipsum.contracts.planner import ChunkSpec, RunPlan
from dataipsum.contracts.sink import ChunkState, RunContext, SinkCapabilities, SinkReceipt
from dataipsum.errors import ProviderUnavailable, SinkError, ValidationError

if TYPE_CHECKING:
    from dataipsum.contracts.executor import LLMLimiter
    from dataipsum.schema.models import ColumnSpec, Schema

OFFENSIVE_MARKER = "#ofensivo"


@dataclass
class FakeSink:
    """Sink em memória (DD-00 §3.11): guarda os batches e simula falha no chunk N."""

    fail_at_chunk: int | None = None
    capabilities: SinkCapabilities = field(
        default_factory=lambda: SinkCapabilities(
            atomic_chunk=True, replace_chunk=True, referential_integrity=False
        )
    )
    _batches: dict[int, pa.RecordBatch | object] = field(
        default_factory=dict, init=False, repr=False
    )

    def open(self, run: RunContext, table: object, arrow_schema: pa.Schema) -> None:
        self._batches.clear()

    def write_chunk(self, chunk_id: int, batch: pa.RecordBatch | object) -> SinkReceipt:
        if chunk_id == self.fail_at_chunk:
            raise SinkError(f"falha simulada no chunk {chunk_id}")
        self._batches[chunk_id] = batch
        return SinkReceipt(sink_ref=f"fake://{chunk_id}")

    def chunk_state(self, chunk_id: int) -> ChunkState:
        return "committed" if chunk_id in self._batches else "absent"

    def close(self) -> None:
        return None

    @property
    def batches(self) -> dict[int, pa.RecordBatch | object]:
        return dict(self._batches)


@dataclass
class _CountingLLMLimiter:
    """Semáforo trivial: só conta quantos `with` foram feitos (DD-00 §3.11)."""

    calls: int = 0

    def __enter__(self) -> _CountingLLMLimiter:
        self.calls += 1
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def _default_run_chunk(task: ChunkTask) -> ChunkResult:
    return ChunkResult(
        table=task.table, chunk_id=task.chunk_spec.id, status="done", rows=task.chunk_spec.rows
    )


@dataclass
class FakeExecutor:
    """Executor em série, no mesmo processo (DD-00 §3.11); `llm_limiter` é um contador."""

    run_chunk: Callable[[ChunkTask], ChunkResult] = _default_run_chunk
    _concurrency: int = field(default=1, init=False, repr=False)
    _limiters: dict[str, _CountingLLMLimiter] = field(default_factory=dict, init=False, repr=False)

    def submit(self, tasks: Iterable[ChunkTask]) -> Iterator[ChunkResult]:
        return (self.run_chunk(task) for task in tasks)

    def set_concurrency(self, n: int) -> None:
        self._concurrency = n

    @property
    def concurrency(self) -> int:
        return self._concurrency

    def shutdown(self, wait: bool) -> None:
        return None

    def llm_limiter(self, provider_name: str, max_concurrency: int) -> LLMLimiter:
        return self._limiters.setdefault(provider_name, _CountingLLMLimiter())


@dataclass
class FakeLLM:
    """Provedor LLM roteirizado (DD-00 §3.11): respostas ou erros em fila, na ordem dada."""

    responses: Sequence[LLMResponse | Exception]
    supports_json_schema: bool = True
    supports_seed: bool = True
    _next_index: int = field(default=0, init=False, repr=False)

    def complete(self, req: LLMRequest) -> LLMResponse:
        if self._next_index >= len(self.responses):
            raise ProviderUnavailable("FakeLLM esgotou as respostas roteirizadas")
        response = self.responses[self._next_index]
        self._next_index += 1
        if isinstance(response, Exception):
            raise response
        return response


@dataclass
class FakeToxicity:
    """Classificador determinístico (DD-00 §3.11): marca `"#ofensivo"` como tóxico máximo."""

    name: str = "fake"

    def score(self, texts: list[str]) -> list[float]:
        return [1.0 if OFFENSIVE_MARKER in text else 0.0 for text in texts]

    def available(self) -> bool:
        return True


@dataclass
class FakePlanner:
    """Planner mínimo (DD-00 §3.11): só tabelas raiz (sem `rows_from`); `pk_at` é uma sequência."""

    def validate(self, schema: Schema) -> list[ValidationError]:
        return []

    def implied_columns(self, table: object) -> list[ColumnSpec]:
        return []

    def plan(self, schema: Schema, seed: int, chunk_size: int) -> RunPlan:
        raise NotImplementedError("FakePlanner não monta RunPlan; use FakeExecutor diretamente")

    def pk_at(self, table: str, indices: NDArray[np.int64]) -> pa.Array:
        return pa.array(indices)

    def parent_index_of(self, table: str, chunk: ChunkSpec, batch: object) -> NDArray[np.int64]:
        raise NotImplementedError("FakePlanner só suporta tabelas raiz, sem rows_from")

    def row_at(
        self, table: str, indices: NDArray[np.int64], columns: list[str]
    ) -> dict[str, pa.Array]:
        raise NotImplementedError("FakePlanner só suporta tabelas raiz, sem rows_from")

    def parent_index_for_ref(
        self, table: str, column: str, indices: NDArray[np.int64]
    ) -> NDArray[np.int64]:
        raise NotImplementedError("FakePlanner só suporta tabelas raiz, sem rows_from")


@dataclass
class SchemaBuilder:
    """Builder fluente de schemas de teste (DD-00 §3.11), no formato do §3.3.

    Devolve um `dict` (não um `Schema`) — ver a nota do módulo sobre por quê.
    """

    _name: str = "dataipsum_teste"
    _seed: int | None = None
    _chunk_size: int = 10_000
    _tables: list[dict[str, object]] = field(default_factory=list)

    def with_name(self, name: str) -> SchemaBuilder:
        self._name = name
        return self

    def with_seed(self, seed: int) -> SchemaBuilder:
        self._seed = seed
        return self

    def with_chunk_size(self, chunk_size: int) -> SchemaBuilder:
        self._chunk_size = chunk_size
        return self

    def with_root_table(
        self,
        name: str,
        rows: int,
        columns: Sequence[dict[str, object]],
        *,
        pk_column: str = "id",
    ) -> SchemaBuilder:
        self._tables.append(
            {
                "name": name,
                "rows": rows,
                "primary_key": {"columns": [pk_column], "strategy": "sequence", "start": 1},
                "columns": list(columns),
            }
        )
        return self

    def build(self) -> dict[str, object]:
        """Ponto único de construção do `dict` final: isola a costura entre-steps (§3.3)."""
        optional_seed = {} if self._seed is None else {"seed": self._seed}
        return {
            "version": 1,
            "name": self._name,
            "chunk_size": self._chunk_size,
            "tables": list(self._tables),
            **optional_seed,
        }
