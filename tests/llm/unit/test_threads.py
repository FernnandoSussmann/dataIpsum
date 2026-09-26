"""Testes de conteúdo de threads (DD-01 §C.3.8, §C.6, C-10)."""

from __future__ import annotations

import json

import pytest

from dataipsum.contracts.llm import LLMResponse
from dataipsum.errors import SchemaError
from dataipsum.llm.filler import LLMEngine
from dataipsum.llm.retry import CircuitBreaker, RetryPolicy
from dataipsum.llm.threads import ThreadFiller, ThreadLLMConfig, ThreadMessage, thread_llm_config
from dataipsum.testing.fakes import FakeToxicity


def _engine(provider) -> LLMEngine:
    return LLMEngine(
        providers={"local": provider},
        toxicity_classifier=FakeToxicity(),
        toxicity_threshold=0.5,
        retry_policy=RetryPolicy(max_attempts=1),
        circuit_breaker=CircuitBreaker(),
    )


_MESSAGES = [ThreadMessage(seq=i + 1, autor_label=f"participante_{i % 2}") for i in range(6)]
_CONFIG = ThreadLLMConfig(
    provider="local",
    prompt=None,
    system=None,
    toxicity="block",
    toxicity_ratio=None,
    on_failure="pending",
    max_regenerations=2,
    max_length=None,
)


def test_thread_llm_config_rejeita_mode_e_pool_size() -> None:
    with pytest.raises(SchemaError):
        thread_llm_config({"llm": {"mode": "pool"}}, default_provider="local")
    with pytest.raises(SchemaError):
        thread_llm_config({"llm": {"pool_size": 10}}, default_provider="local")


def test_thread_llm_config_usa_defaults() -> None:
    config = thread_llm_config(None, default_provider="local")
    assert config.provider == "local"
    assert config.toxicity == "block"
    assert config.on_failure == "pending"


def test_c10_json_invalido_cai_no_fallback_mensagem_a_mensagem() -> None:
    class _NeverJSON:
        supports_json_schema = True
        supports_seed = True
        model = "m"

        def complete(self, req):  # type: ignore[no-untyped-def]
            return LLMResponse(text="isso não é JSON", finish_reason="stop")

    filler = ThreadFiller(_engine(_NeverJSON()))
    outcome = filler.fill(
        _CONFIG, thread_seed=1, subject_context={"titulo": "assunto"}, messages=_MESSAGES
    )
    assert outcome.status == "done"
    assert outcome.used_fallback is True
    assert len(outcome.texts) == 6
    assert all(text for text in outcome.texts)


def test_json_estruturado_com_n_mensagens_e_aceito() -> None:
    payload = {"mensagens": [{"seq": m.seq, "texto": f"mensagem {m.seq}"} for m in _MESSAGES]}

    class _ValidJSON:
        supports_json_schema = True
        supports_seed = True
        model = "m"

        def complete(self, req):  # type: ignore[no-untyped-def]
            return LLMResponse(text=json.dumps(payload), finish_reason="stop")

    filler = ThreadFiller(_engine(_ValidJSON()))
    outcome = filler.fill(
        _CONFIG, thread_seed=1, subject_context={"titulo": "assunto"}, messages=_MESSAGES
    )
    assert outcome.status == "done"
    assert outcome.used_fallback is False
    assert outcome.texts == [f"mensagem {m.seq}" for m in _MESSAGES]


def test_json_com_mais_de_n_itens_e_truncado() -> None:
    payload = {
        "mensagens": [{"seq": m.seq, "texto": f"mensagem {m.seq}"} for m in _MESSAGES]
        + [{"seq": 99, "texto": "sobra"}]
    }

    class _ExtraJSON:
        supports_json_schema = True
        supports_seed = True
        model = "m"

        def complete(self, req):  # type: ignore[no-untyped-def]
            return LLMResponse(text=json.dumps(payload), finish_reason="stop")

    filler = ThreadFiller(_engine(_ExtraJSON()))
    outcome = filler.fill(
        _CONFIG, thread_seed=1, subject_context={"titulo": "assunto"}, messages=_MESSAGES
    )
    assert len(outcome.texts) == 6
    assert "sobra" not in (outcome.texts or [])


def test_toxicidade_por_mensagem_bloqueia_so_a_mensagem_ofensiva() -> None:
    payload_offensive = {
        "mensagens": [
            {"seq": m.seq, "texto": "#ofensivo" if m.seq == 3 else f"mensagem {m.seq}"}
            for m in _MESSAGES
        ]
    }

    class _OffensiveThenClean:
        supports_json_schema = True
        supports_seed = True
        model = "m"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, req):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(text=json.dumps(payload_offensive), finish_reason="stop")
            return LLMResponse(text="mensagem regenerada limpa", finish_reason="stop")

    provider = _OffensiveThenClean()
    filler = ThreadFiller(_engine(provider))
    outcome = filler.fill(
        _CONFIG, thread_seed=1, subject_context={"titulo": "assunto"}, messages=_MESSAGES
    )
    assert outcome.status == "done"
    assert outcome.is_offensive == [False] * 6
    assert outcome.texts[2] == "mensagem regenerada limpa"
    assert outcome.texts[0] == "mensagem 1"


def test_thread_fallbacks_quando_esgota_regeneracao() -> None:
    class _AlwaysOffensive:
        supports_json_schema = True
        supports_seed = True
        model = "m"

        def complete(self, req):  # type: ignore[no-untyped-def]
            payload = {"mensagens": [{"seq": m.seq, "texto": "#ofensivo"} for m in _MESSAGES]}
            return LLMResponse(text=json.dumps(payload), finish_reason="stop")

    filler = ThreadFiller(_engine(_AlwaysOffensive()))
    outcome = filler.fill(
        _CONFIG, thread_seed=1, subject_context={"titulo": "assunto"}, messages=_MESSAGES
    )
    assert outcome.status == "pending_llm"
    assert outcome.texts == [None] * 6
