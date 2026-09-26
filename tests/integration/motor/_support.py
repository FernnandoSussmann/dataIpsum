"""Suporte da integração do motor (DD-01 §3, S5): `Sink` de teste que persiste em disco (para
poder ler os dados de volta e checar integridade referencial/hash, já que cada chunk roda num
processo `spawn` separado — nada além do `ChunkResult` volta ao processo do teste) e o
`run_chunk` picklable que troca os fakes internos (`FakeLLM`/`FakeToxicity`) pelos reais de A/B/D.

`FakeSink`/`FakeLLM`/`FakeToxicity` são os fakes de `dataipsum.testing.fakes` (DD-00 §3.11); a
integração S5 "usa `FakeSink`, `FakeLLM` e `FakeToxicity` — não depende do DD-02" (DD-01 §3).
`HashingFileSink` abaixo é o mesmo tipo de fake (grava em memória seria perdido entre
processos), só que grava em arquivo para o teste poder ler de volta; não é um sink de produção.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.ipc as pa_ipc

from dataipsum.contracts.executor import ChunkResult
from dataipsum.contracts.llm import LLMResponse
from dataipsum.contracts.sink import ChunkState, RunContext, SinkCapabilities, SinkReceipt
from dataipsum.execution import chunk_builder
from dataipsum.llm.filler import LLMEngine
from dataipsum.llm.retry import CircuitBreaker, RetryPolicy
from dataipsum.registry import build_registry
from dataipsum.relations import RelationsPlanner
from dataipsum.testing.fakes import FakeLLM, FakeToxicity

if TYPE_CHECKING:
    from dataipsum.contracts.executor import ChunkTask

SINK_KIND = "golden_file"

# `max_attempts=1` e sem espera: a simulação de falha do FakeLLM (I-04) não deve gastar tempo
# real em backoff — o teste quer a falha imediata, não o retry em si (isso já é coberto pelos
# testes unitários de `dataipsum.llm.retry`, trilha C).
_FAST_RETRY = RetryPolicy(max_attempts=1, base_delay_s=0.0, max_delay_s=0.0)


@dataclass
class HashingFileSink:
    """`Sink` de teste (DD-00 §3.11, mesmo espírito de `FakeSink`): grava cada chunk como IPC
    do Arrow em `<out_dir>/_data/<tabela>/<chunk_id>.arrow` e devolve o sha256 do conteúdo —
    necessário porque `FakeSink` guarda os batches só em memória, perdidos entre os processos
    `spawn` do `LocalExecutor` (DD-01 §D.3.3)."""

    out_dir: str
    table: str
    capabilities: SinkCapabilities = field(
        default_factory=lambda: SinkCapabilities(
            atomic_chunk=True, replace_chunk=True, referential_integrity=False
        )
    )

    def open(self, run: RunContext, table: object, arrow_schema: pa.Schema) -> None:
        self._table_dir().mkdir(parents=True, exist_ok=True)

    def _table_dir(self) -> Path:
        return Path(self.out_dir) / "_data" / self.table

    def _chunk_path(self, chunk_id: int) -> Path:
        return self._table_dir() / f"{chunk_id}.arrow"

    def write_chunk(self, chunk_id: int, batch: pa.RecordBatch | object) -> SinkReceipt:
        assert isinstance(batch, pa.RecordBatch)
        self._table_dir().mkdir(parents=True, exist_ok=True)
        sink = pa.BufferOutputStream()
        with pa_ipc.new_stream(sink, batch.schema) as writer:
            writer.write_batch(batch)
        content = sink.getvalue().to_pybytes()
        path = self._chunk_path(chunk_id)
        path.write_bytes(content)
        return SinkReceipt(sink_ref=str(path), sha256=hashlib.sha256(content).hexdigest())

    def chunk_state(self, chunk_id: int) -> ChunkState:
        return "committed" if self._chunk_path(chunk_id).exists() else "absent"

    def close(self) -> None:
        return None


def read_table(out_dir: Path, table: str) -> pa.Table:
    """Lê de volta todos os chunks gravados de `table` (usado pelos testes, não pelo motor)."""
    table_dir = out_dir / "_data" / table
    batches = []
    for path in sorted(table_dir.glob("*.arrow"), key=lambda p: int(p.stem)):
        with pa_ipc.open_stream(path.read_bytes()) as reader:
            batches.extend(reader.read_all().to_batches())
    return pa.Table.from_batches(batches) if batches else pa.table({})


@dataclass(frozen=True)
class GoldenRunChunk:
    """`run_chunk` picklable (DD-01 §D.3.3) da integração: registry real de A/B (tipos +
    relações) via `build_registry`, mas motor LLM com `FakeLLM`/`FakeToxicity` (DD-00 §3.11) em
    vez dos provedores reais — a coluna 'kind' do provedor no schema (`ollama`, só para passar a
    validação Pydantic de `LLMProviderConfig.kind`) é ignorada aqui de propósito."""

    llm_response_texts: tuple[str, ...]

    def __call__(self, task: ChunkTask) -> ChunkResult:
        registry = build_registry()
        registry.register_sink(SINK_KIND, HashingFileSink, origin="teste-integracao-motor")
        generators = {name: generator_cls() for name, generator_cls in registry.generators.items()}
        planner = RelationsPlanner(generators=generators)
        planner.plan(task.schema, task.root_seed, task.schema.chunk_size)

        engine = self._build_engine(task)
        sink_kind = str(task.sink_options["kind"])
        sink_cls = registry.get_sink(sink_kind)
        sink_options = dict(task.sink_options.get("options", {}))
        sink = sink_cls(**sink_options, table=task.table)  # type: ignore[call-arg]

        return chunk_builder.build_chunk(
            task, planner=planner, registry=registry, sink=sink, llm_engine=engine
        )

    def _build_engine(self, task: ChunkTask) -> LLMEngine | None:
        if task.schema.llm is None:
            return None
        responses = [
            LLMResponse(text=text, finish_reason="stop") for text in self.llm_response_texts
        ]
        providers = {name: FakeLLM(responses=list(responses)) for name in task.schema.llm.providers}
        return LLMEngine(
            providers=providers,
            toxicity_classifier=FakeToxicity(),
            toxicity_threshold=0.5,
            retry_policy=_FAST_RETRY,
            circuit_breaker=CircuitBreaker(),
        )
