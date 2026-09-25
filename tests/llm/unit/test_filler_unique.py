"""Testes do modo `unique` (DD-01 §C.6, C-01 a C-04, C-08, C-09, C-14, C-16)."""

from __future__ import annotations

from dataipsum import seeds
from dataipsum.contracts.llm import LLMResponse
from dataipsum.errors import ProviderUnavailable
from dataipsum.llm.filler import (
    LLMEngine,
    RowContext,
    fill_unique_column,
    max_tokens_for,
)
from dataipsum.llm.retry import CircuitBreaker, RetryPolicy
from dataipsum.testing.fakes import FakeLLM, FakeToxicity


def _engine(provider, *, threshold: float = 0.5) -> LLMEngine:
    return LLMEngine(
        providers={"local": provider},
        toxicity_classifier=FakeToxicity(),
        toxicity_threshold=threshold,
        retry_policy=RetryPolicy(max_attempts=2),
        circuit_breaker=CircuitBreaker(),
    )


def _rows(n: int) -> list[RowContext]:
    return [
        RowContext(row=i, same_row={}, parent_rows={"autor_id": {"nome": f"Autor{i}"}})
        for i in range(n)
    ]


def test_c01_texto_nao_vazio_e_respeita_max_length(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=20)
    column = posts.columns[-1]
    provider = FakeLLM(
        responses=[LLMResponse(text="x" * 100, finish_reason="stop") for _ in range(5)]
    )
    engine = _engine(provider)
    outcome = fill_unique_column(engine, schema, posts, column, _rows(5), root_seed=1)
    assert outcome.status == "done"
    assert all(text for text in outcome.texts)
    assert all(len(text) <= 20 for text in outcome.texts if text is not None)


def test_c02_variavel_do_pai_e_substituida_no_prompt(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema()
    column = posts.model_copy(
        update={
            "columns": [
                *posts.columns[:-1],
                posts.columns[-1].model_copy(
                    update={"params": {"provider": "local", "prompt": "Post de {autor_id.nome}"}}
                ),
            ]
        }
    ).columns[-1]
    captured_prompts: list[str] = []

    class _EchoProvider:
        supports_json_schema = True
        supports_seed = True
        model = "echo"

        def complete(self, req):  # type: ignore[no-untyped-def]
            captured_prompts.append(req.prompt)
            return LLMResponse(text=req.prompt, finish_reason="stop")

    engine = _engine(_EchoProvider())
    rows = [RowContext(row=0, same_row={}, parent_rows={"autor_id": {"nome": "Fernanda"}})]
    outcome = fill_unique_column(engine, schema, posts, column, rows, root_seed=1)
    assert outcome.status == "done"
    assert "Fernanda" in captured_prompts[0]
    assert outcome.texts[0] is not None and "Fernanda" in outcome.texts[0]


def test_seed_por_linha_e_seed_llm(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = posts.columns[-1]
    seeds_used: list[int | None] = []

    class _RecordingProvider:
        supports_json_schema = True
        supports_seed = True
        model = "rec"

        def complete(self, req):  # type: ignore[no-untyped-def]
            seeds_used.append(req.seed)
            return LLMResponse(text="ok", finish_reason="stop")

    engine = _engine(_RecordingProvider())
    outcome = fill_unique_column(engine, schema, posts, column, _rows(3), root_seed=123)
    assert outcome.status == "done"

    seed_col = seeds.seed_column(seeds.seed_table(123, "posts"), "conteudo")
    expected = [seeds.seed_llm(seed_col, row) for row in range(3)]
    assert seeds_used == expected


def test_truncamento_na_fronteira_de_palavra(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=10)
    column = posts.columns[-1]
    provider = FakeLLM(
        responses=[LLMResponse(text="uma frase razoavelmente longa aqui", finish_reason="stop")]
    )
    engine = _engine(provider)
    outcome = fill_unique_column(engine, schema, posts, column, _rows(1), root_seed=1)
    assert outcome.texts[0] == "uma frase"  # corta na última fronteira de palavra <= 10
    assert len(outcome.texts[0]) <= 10


def test_c04_toxicity_block_nunca_deixa_ofensivo_passar(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = posts.columns[-1].model_copy(
        update={"params": {"provider": "local", "toxicity": "block", "max_regenerations": 3}}
    )
    # primeira resposta ofensiva, segunda limpa.
    provider = FakeLLM(
        responses=[
            LLMResponse(text="#ofensivo", finish_reason="stop"),
            LLMResponse(text="texto limpo", finish_reason="stop"),
        ]
    )
    engine = _engine(provider)
    outcome = fill_unique_column(engine, schema, posts, column, _rows(1), root_seed=1)
    assert outcome.status == "done"
    assert outcome.is_offensive == [False]
    assert outcome.texts[0] == "texto limpo"


def test_c14_bloqueio_esgotado_fica_pending_mesmo_com_placeholder(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = posts.columns[-1].model_copy(
        update={
            "params": {
                "provider": "local",
                "toxicity": "block",
                "max_regenerations": 2,
                "on_failure": "placeholder",
            }
        }
    )
    provider = FakeLLM(
        responses=[LLMResponse(text="#ofensivo", finish_reason="stop") for _ in range(3)]
    )
    engine = _engine(provider)
    outcome = fill_unique_column(engine, schema, posts, column, _rows(1), root_seed=1)
    assert outcome.status == "pending_llm"
    assert outcome.texts == [None]
    assert outcome.is_placeholder == [False]
    assert outcome.flags.toxicity_exhausted == 1


def test_c08_provedor_indisponivel_fica_pending_llm(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = posts.columns[-1]
    provider = FakeLLM(responses=[ProviderUnavailable("fora do ar")] * 10)
    engine = _engine(provider)
    outcome = fill_unique_column(engine, schema, posts, column, _rows(2), root_seed=1)
    assert outcome.status == "pending_llm"
    assert outcome.texts == [None, None]
    assert outcome.is_placeholder == [False, False]


def test_c09_placeholder_grava_lorem_e_marca_is_placeholder(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = posts.columns[-1].model_copy(
        update={"params": {"provider": "local", "on_failure": "placeholder"}}
    )
    provider = FakeLLM(responses=[ProviderUnavailable("fora do ar")] * 10)
    engine = _engine(provider)
    outcome = fill_unique_column(engine, schema, posts, column, _rows(2), root_seed=1)
    assert outcome.status == "pending_llm"
    assert all(text for text in outcome.texts)
    assert outcome.is_placeholder == [True, True]
    assert outcome.flags.placeholders == 2


def test_c16_motor_nunca_usa_placeholder_sem_pedido_explicito(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = posts.columns[-1]  # on_failure padrão é "pending"
    provider = FakeLLM(responses=[ProviderUnavailable("fora do ar")] * 10)
    engine = _engine(provider)
    outcome = fill_unique_column(engine, schema, posts, column, _rows(1), root_seed=1)
    assert outcome.is_placeholder == [False]
    assert outcome.texts == [None]


def test_toxicity_ratio_proporcao_alvo(parent_child_schema) -> None:
    schema, _usuarios, posts = parent_child_schema(child_max_length=None)
    column = posts.columns[-1].model_copy(
        update={"params": {"provider": "local", "toxicity": "ratio", "toxicity_ratio": 0.1}}
    )
    n = 2000

    class _ObedientProvider:
        supports_json_schema = True
        supports_seed = True
        model = "obediente"

        def complete(self, req):  # type: ignore[no-untyped-def]
            if "TERMINANTEMENTE" in req.system:
                return LLMResponse(text="#ofensivo", finish_reason="stop")
            return LLMResponse(text="texto normal", finish_reason="stop")

    engine = _engine(_ObedientProvider())
    outcome = fill_unique_column(engine, schema, posts, column, _rows(n), root_seed=1)
    assert outcome.status == "done"
    fraction = sum(outcome.is_offensive) / n
    assert abs(fraction - 0.1) < 0.03


def test_max_tokens_for_com_e_sem_max_length() -> None:
    assert max_tokens_for(None) == 2048
    assert max_tokens_for(100) == max(16, 100 // 2 + 64)
