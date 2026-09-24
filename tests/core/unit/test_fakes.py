"""Testes dos fakes de teste (DD-00 §7.1: testing/fakes.py)."""

from __future__ import annotations

import numpy as np
import pytest

from dataipsum.contracts.executor import ChunkResult, ChunkTask
from dataipsum.contracts.llm import LLMRequest, LLMResponse
from dataipsum.contracts.planner import ChunkSpec
from dataipsum.contracts.sink import RunContext
from dataipsum.errors import ProviderUnavailable, SinkError
from dataipsum.testing.fakes import (
    OFFENSIVE_MARKER,
    FakeExecutor,
    FakeLLM,
    FakePlanner,
    FakeSink,
    FakeToxicity,
    SchemaBuilder,
)


def _chunk_task(table: str, chunk_id: int, rows: int) -> ChunkTask:
    return ChunkTask(
        table=table,
        chunk_spec=ChunkSpec(id=chunk_id, first_row=chunk_id * rows, rows=rows),
        schema=object(),
        root_seed=42,
        sink_options={},
        run_options={},
    )


# --- FakeSink -----------------------------------------------------------------


def test_fake_sink_guarda_batches_em_memoria() -> None:
    sink = FakeSink()
    sink.open(RunContext(run_id="r1", out_dir="/tmp/out", seed=1), table=None, arrow_schema=None)
    receipt = sink.write_chunk(0, batch="batch-0")
    assert receipt.sink_ref == "fake://0"
    assert sink.chunk_state(0) == "committed"
    assert sink.chunk_state(1) == "absent"
    assert sink.batches == {0: "batch-0"}
    sink.close()


def test_fake_sink_falha_no_chunk_configurado() -> None:
    sink = FakeSink(fail_at_chunk=2)
    sink.write_chunk(0, batch="ok-0")
    sink.write_chunk(1, batch="ok-1")
    with pytest.raises(SinkError):
        sink.write_chunk(2, batch="vai-falhar")
    assert sink.batches == {0: "ok-0", 1: "ok-1"}
    assert sink.chunk_state(2) == "absent"


# --- FakeExecutor ---------------------------------------------------------------


def test_fake_executor_roda_em_serie_e_preserva_a_ordem() -> None:
    executor = FakeExecutor()
    tasks = [_chunk_task("usuarios", chunk_id, rows=10) for chunk_id in range(3)]
    results = list(executor.submit(tasks))
    assert [r.chunk_id for r in results] == [0, 1, 2]
    assert all(r.status == "done" and r.rows == 10 for r in results)


def test_fake_executor_usa_run_chunk_customizado() -> None:
    def falha_tudo(task: object) -> ChunkResult:
        return ChunkResult(table="usuarios", chunk_id=0, status="failed", rows=0, error="boom")

    executor = FakeExecutor(run_chunk=falha_tudo)
    (result,) = list(executor.submit([_chunk_task("usuarios", 0, rows=1)]))
    assert result.status == "failed"
    assert result.error == "boom"


def test_fake_executor_concurrency_e_configuravel() -> None:
    executor = FakeExecutor()
    assert executor.concurrency == 1
    executor.set_concurrency(4)
    assert executor.concurrency == 4
    executor.shutdown(wait=True)


def test_fake_executor_llm_limiter_e_um_contador_por_provedor() -> None:
    executor = FakeExecutor()
    limiter = executor.llm_limiter("local", max_concurrency=2)
    with limiter:
        pass
    with executor.llm_limiter("local", max_concurrency=2):
        pass
    assert limiter.calls == 2
    outro_provedor = executor.llm_limiter("nuvem", max_concurrency=1)
    assert outro_provedor.calls == 0
    assert outro_provedor is not limiter


# --- FakeLLM ---------------------------------------------------------------------


def _request() -> LLMRequest:
    return LLMRequest(system="s", prompt="p", max_tokens=10, temperature=0.0)


def test_fake_llm_devolve_respostas_na_ordem() -> None:
    llm = FakeLLM(
        responses=[
            LLMResponse(text='{"ok": true}', finish_reason="stop"),
            LLMResponse(text="texto invalido {", finish_reason="stop"),
        ]
    )
    primeira = llm.complete(_request())
    segunda = llm.complete(_request())
    assert primeira.text == '{"ok": true}'
    assert segunda.text == "texto invalido {"


def test_fake_llm_levanta_falha_programada() -> None:
    llm = FakeLLM(responses=[ProviderUnavailable("indisponível")])
    with pytest.raises(ProviderUnavailable):
        llm.complete(_request())


def test_fake_llm_esgotado_levanta_provider_unavailable() -> None:
    llm = FakeLLM(responses=[])
    with pytest.raises(ProviderUnavailable):
        llm.complete(_request())


# --- FakeToxicity ------------------------------------------------------------------


def test_fake_toxicity_marca_texto_ofensivo() -> None:
    toxicity = FakeToxicity()
    scores = toxicity.score(["oi tudo bem", f"comentário {OFFENSIVE_MARKER} aqui"])
    assert scores == [0.0, 1.0]
    assert toxicity.available() is True


# --- FakePlanner ------------------------------------------------------------------


def test_fake_planner_pk_at_e_sequencia() -> None:
    planner = FakePlanner()
    indices = np.array([5, 6, 7], dtype=np.int64)
    pk_values = planner.pk_at("usuarios", indices)
    assert pk_values.to_pylist() == [5, 6, 7]


def test_fake_planner_sem_relacoes_de_filhos() -> None:
    planner = FakePlanner()
    assert planner.validate(schema=object()) == []
    assert planner.implied_columns(table=object()) == []
    chunk = ChunkSpec(id=0, first_row=0, rows=1)
    with pytest.raises(NotImplementedError):
        planner.parent_index_of("pedidos", chunk, batch=None)
    with pytest.raises(NotImplementedError):
        planner.row_at("usuarios", np.array([0], dtype=np.int64), ["id"])
    with pytest.raises(NotImplementedError):
        planner.plan(schema=object(), seed=1, chunk_size=100)


# --- SchemaBuilder ------------------------------------------------------------------


def test_schema_builder_produz_schema_valido_no_formato_3_3() -> None:
    schema = (
        SchemaBuilder()
        .with_name("loja")
        .with_seed(42)
        .with_chunk_size(500)
        .with_root_table(
            "usuarios",
            rows=10,
            columns=[{"name": "id", "type": "int"}, {"name": "nome", "type": "nome_proprio"}],
        )
        .build()
    )
    assert schema["version"] == 1
    assert schema["name"] == "loja"
    assert schema["seed"] == 42
    assert schema["chunk_size"] == 500
    (table,) = schema["tables"]
    assert table["name"] == "usuarios"
    assert table["rows"] == 10
    assert table["primary_key"] == {"columns": ["id"], "strategy": "sequence", "start": 1}
    assert [c["name"] for c in table["columns"]] == ["id", "nome"]


def test_schema_builder_omite_seed_quando_ausente() -> None:
    schema = SchemaBuilder().with_root_table("t", rows=1, columns=[]).build()
    assert "seed" not in schema
