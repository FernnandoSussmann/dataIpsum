"""Testes de retry/backoff e circuit breaker (DD-01 §C.6)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from dataipsum.contracts.llm import LLMRequest, LLMResponse
from dataipsum.errors import ProviderRefusal, ProviderUnavailable
from dataipsum.llm.retry import (
    CircuitBreaker,
    CircuitOpenError,
    RetryPolicy,
    backoff_delay,
    call_with_retry,
)


@dataclass
class _FlakyProvider:
    """Falha `fail_times` vezes e depois responde com sucesso."""

    fail_times: int
    response_text: str = "ok"
    calls: int = field(default=0, init=False)
    supports_json_schema: bool = True
    supports_seed: bool = True

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderUnavailable("indisponível")
        return LLMResponse(text=self.response_text, finish_reason="stop")


@dataclass
class _AlwaysFailProvider:
    calls: int = field(default=0, init=False)
    supports_json_schema: bool = True
    supports_seed: bool = True

    def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls += 1
        raise ProviderUnavailable("sempre indisponível")


_REQUEST = LLMRequest(system="s", prompt="p", max_tokens=64, temperature=0.0, seed=1)


def test_backoff_delay_e_determinista_por_seed_chunk_e_attempt() -> None:
    a = backoff_delay(42, 2, base_delay_s=1.0, max_delay_s=60.0)
    b = backoff_delay(42, 2, base_delay_s=1.0, max_delay_s=60.0)
    assert a == b


def test_backoff_delay_varia_com_o_attempt() -> None:
    delays = {
        backoff_delay(42, attempt, base_delay_s=1.0, max_delay_s=60.0) for attempt in range(5)
    }
    assert len(delays) > 1


def test_backoff_delay_respeita_o_teto() -> None:
    delay = backoff_delay(1, 10, base_delay_s=1.0, max_delay_s=5.0)
    assert 0.0 <= delay <= 5.0


def test_call_with_retry_reusa_apos_falhas_transitorias() -> None:
    provider = _FlakyProvider(fail_times=2)
    response = call_with_retry(
        provider, _REQUEST, policy=RetryPolicy(max_attempts=5), seed_chunk=7, sleep=lambda _s: None
    )
    assert response.text == "ok"
    assert provider.calls == 3


def test_call_with_retry_esgota_tentativas_e_levanta() -> None:
    provider = _AlwaysFailProvider()
    with pytest.raises(ProviderUnavailable):
        call_with_retry(
            provider,
            _REQUEST,
            policy=RetryPolicy(max_attempts=3),
            seed_chunk=7,
            sleep=lambda _s: None,
        )
    assert provider.calls == 3


def test_retry_after_e_respeitado() -> None:
    class _RateLimited:
        supports_json_schema = True
        supports_seed = True

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, req: LLMRequest) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                from dataipsum.errors import ProviderRateLimited

                error = ProviderRateLimited("429")
                error.retry_after = 12.5  # type: ignore[attr-defined]
                raise error
            return LLMResponse(text="ok", finish_reason="stop")

    provider = _RateLimited()
    sleeps: list[float] = []
    call_with_retry(
        provider, _REQUEST, policy=RetryPolicy(max_attempts=3), seed_chunk=1, sleep=sleeps.append
    )
    assert sleeps == [12.5]


def test_refusal_e_retentada_uma_vez_e_depois_conta_como_falha() -> None:
    class _AlwaysRefuses:
        supports_json_schema = True
        supports_seed = True

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, req: LLMRequest) -> LLMResponse:
            self.calls += 1
            raise ProviderRefusal("recusado")

    provider = _AlwaysRefuses()
    with pytest.raises(ProviderRefusal):
        call_with_retry(
            provider,
            _REQUEST,
            policy=RetryPolicy(max_attempts=5),
            seed_chunk=1,
            sleep=lambda _s: None,
        )
    assert provider.calls == 2


def test_circuit_breaker_abre_apos_3_chunks_consecutivos_com_falha() -> None:
    breaker = CircuitBreaker(threshold=3)
    breaker.record_chunk_failure("local")
    breaker.record_chunk_failure("local")
    assert breaker.is_open("local") is False
    breaker.record_chunk_failure("local")
    assert breaker.is_open("local") is True


def test_circuit_breaker_sucesso_reseta_contagem() -> None:
    breaker = CircuitBreaker(threshold=3)
    breaker.record_chunk_failure("local")
    breaker.record_chunk_failure("local")
    breaker.record_chunk_success("local")
    breaker.record_chunk_failure("local")
    breaker.record_chunk_failure("local")
    assert breaker.is_open("local") is False


def test_circuito_aberto_nao_chama_o_provedor() -> None:
    provider = _AlwaysFailProvider()
    breaker = CircuitBreaker(threshold=1)
    with pytest.raises(ProviderUnavailable):
        call_with_retry(
            provider,
            _REQUEST,
            policy=RetryPolicy(max_attempts=1),
            seed_chunk=1,
            circuit_breaker=breaker,
            provider_name="local",
            sleep=lambda _s: None,
        )
    assert breaker.is_open("local") is True
    calls_before = provider.calls
    with pytest.raises(CircuitOpenError):
        call_with_retry(
            provider,
            _REQUEST,
            policy=RetryPolicy(max_attempts=5),
            seed_chunk=1,
            circuit_breaker=breaker,
            provider_name="local",
            sleep=lambda _s: None,
        )
    assert provider.calls == calls_before
