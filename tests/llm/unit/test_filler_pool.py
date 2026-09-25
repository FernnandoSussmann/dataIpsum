"""Testes do modo `pool` (DD-01 §C.6, C-06, C-07)."""

from __future__ import annotations

from pathlib import Path

from dataipsum.contracts.llm import LLMResponse
from dataipsum.llm.cache import DiskCache
from dataipsum.llm.filler import LLMEngine, PoolBuilder, RowContext, fill_pool_column
from dataipsum.llm.retry import CircuitBreaker, RetryPolicy
from dataipsum.testing.fakes import FakeLLM, FakeToxicity


def _engine(provider, *, cache: DiskCache | None = None) -> LLMEngine:
    return LLMEngine(
        providers={"local": provider},
        toxicity_classifier=FakeToxicity(),
        toxicity_threshold=0.5,
        retry_policy=RetryPolicy(max_attempts=2),
        circuit_breaker=CircuitBreaker(),
        cache=cache,
    )


def _pool_column(posts, *, pool_size: int = 10, toxicity: str = "block", toxicity_ratio=None):
    return posts.columns[-1].model_copy(
        update={
            "params": {
                "provider": "local",
                "prompt": "Escreva sobre {autor_id.nome}",
                "mode": "pool",
                "pool_size": pool_size,
                "toxicity": toxicity,
                **({"toxicity_ratio": toxicity_ratio} if toxicity_ratio is not None else {}),
            }
        }
    )


def test_c06_pool_faz_exatamente_pool_size_chamadas(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = _pool_column(posts, pool_size=10)
    calls = {"n": 0}

    class _CountingProvider:
        supports_json_schema = True
        supports_seed = True
        model = "count"

        def complete(self, req):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return LLMResponse(text="texto do pool para {autor_id.nome}", finish_reason="stop")

    builder = PoolBuilder(_engine(_CountingProvider()))
    pool = builder.build(schema, posts, column, root_seed=1)
    assert calls["n"] == 10
    assert len(pool.texts) == 10


def test_pool_marcador_desconhecido_causa_regeneracao_e_descarte(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = _pool_column(posts, pool_size=1)
    # sempre devolve um marcador desconhecido -> esgota regenerações -> descartado.
    provider = FakeLLM(
        responses=[
            LLMResponse(text="texto com {marcador_invalido}", finish_reason="stop")
            for _ in range(10)
        ]
    )
    builder = PoolBuilder(_engine(provider))
    pool = builder.build(schema, posts, column, root_seed=1)
    assert pool.texts == ()


def test_pool_preenchimento_por_linha_e_deterministico(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = _pool_column(posts, pool_size=3)
    provider = FakeLLM(
        responses=[
            LLMResponse(text="Ola {autor_id.nome}, item A", finish_reason="stop"),
            LLMResponse(text="Ola {autor_id.nome}, item B", finish_reason="stop"),
            LLMResponse(text="Ola {autor_id.nome}, item C", finish_reason="stop"),
        ]
    )
    builder = PoolBuilder(_engine(provider))
    pool = builder.build(schema, posts, column, root_seed=1)
    assert len(pool.texts) == 3

    rows = [
        RowContext(row=i, same_row={}, parent_rows={"autor_id": {"nome": f"P{i}"}})
        for i in range(20)
    ]
    outcome_a = fill_pool_column(pool, schema, posts, column, rows, root_seed=1)
    outcome_b = fill_pool_column(pool, schema, posts, column, rows, root_seed=1)
    assert outcome_a.texts == outcome_b.texts  # mesma seed => mesma escolha
    assert all(f"P{i}" in (text or "") for i, text in enumerate(outcome_a.texts))


def test_c07_segunda_execucao_com_cache_nao_chama_o_provedor(
    parent_child_schema, tmp_path: Path
) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = _pool_column(posts, pool_size=2)
    calls = {"n": 0}

    class _CountingProvider:
        supports_json_schema = True
        supports_seed = True
        model = "count"

        def complete(self, req):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return LLMResponse(text="texto fixo, sem marcador", finish_reason="stop")

    cache = DiskCache(cache_dir=tmp_path)
    engine = _engine(_CountingProvider(), cache=cache)
    builder = PoolBuilder(engine)
    builder.build(schema, posts, column, root_seed=1)
    assert calls["n"] == 2

    # segunda execução: mesmo cache_dir, mesma seed => tudo vem do cache.
    builder_2 = PoolBuilder(engine)
    builder_2.build(schema, posts, column, root_seed=1)
    assert calls["n"] == 2  # não cresceu
