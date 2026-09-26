"""Retry com backoff exponencial (full jitter) e circuit breaker por provedor (DD-01 §C.3.1)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from dataipsum import seeds
from dataipsum.contracts.llm import LLMProvider, LLMRequest, LLMResponse
from dataipsum.errors import (
    LLMError,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderRefusal,
    ProviderUnavailable,
)

# Slot reservado ao jitter de retry (DD-00 §3.6: slots 2..63 livres para uso de cada trilha).
_JITTER_SLOT = 40

RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    ProviderUnavailable,
    ProviderRateLimited,
    ProviderBadResponse,
)


class CircuitOpenError(LLMError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0


def backoff_delay(
    seed_chunk: int, attempt: int, *, base_delay_s: float, max_delay_s: float
) -> float:
    """`delay = U(0, min(max_delay_s, base_delay_s * 2**attempt))`, jitter de `seed_chunk`.

    O jitter é sorteado por `dataipsum.seeds` (nunca `random`/`numpy.random`), com `attempt`
    como "linha": determinístico por `(seed_chunk, attempt)`, mas não vira dado de saída.
    """
    cap = min(max_delay_s, base_delay_s * (2.0**attempt))
    row = np.array([attempt], dtype=np.int64)
    jitter = float(seeds.uniform(seed_chunk, row, _JITTER_SLOT)[0])
    return jitter * cap


@dataclass
class CircuitBreaker:
    """Abre para o resto da execução depois de `threshold` chunks consecutivos com falha
    definitiva no mesmo provedor (§C.3.1)."""

    threshold: int = 3
    _consecutive_failures: dict[str, int] = field(default_factory=dict, repr=False)
    _open: set[str] = field(default_factory=set, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def is_open(self, provider_name: str) -> bool:
        with self._lock:
            return provider_name in self._open

    def record_chunk_failure(self, provider_name: str) -> None:
        with self._lock:
            count = self._consecutive_failures.get(provider_name, 0) + 1
            self._consecutive_failures[provider_name] = count
            if count >= self.threshold:
                self._open.add(provider_name)

    def record_chunk_success(self, provider_name: str) -> None:
        with self._lock:
            self._consecutive_failures[provider_name] = 0


def call_with_retry(
    provider: LLMProvider,
    request: LLMRequest,
    *,
    policy: RetryPolicy,
    seed_chunk: int,
    circuit_breaker: CircuitBreaker | None = None,
    provider_name: str = "default",
    sleep: Callable[[float], None] = time.sleep,
) -> LLMResponse:
    """Chama `provider.complete` com retry/backoff; registra sucesso/falha no `circuit_breaker`.

    Levanta `CircuitOpenError` sem chamar o provedor se o circuito já estiver aberto (§C.3.1,
    "os chunks LLM seguintes vão direto para o tratamento de falha, sem esperar retries").
    """
    if circuit_breaker is not None and circuit_breaker.is_open(provider_name):
        raise CircuitOpenError(
            f"circuito aberto para o provedor '{provider_name}' (falhas consecutivas anteriores)"
        )

    refusal_retried = False
    last_error: Exception | None = None
    for attempt in range(policy.max_attempts):
        try:
            response = provider.complete(request)
        except ProviderRefusal as exc:
            last_error = exc
            if refusal_retried:
                break
            refusal_retried = True
            continue
        except RETRYABLE_ERRORS as exc:
            last_error = exc
            if attempt + 1 >= policy.max_attempts:
                break
            retry_after = getattr(exc, "retry_after", None)
            delay = (
                float(retry_after)
                if retry_after is not None
                else backoff_delay(
                    seed_chunk,
                    attempt,
                    base_delay_s=policy.base_delay_s,
                    max_delay_s=policy.max_delay_s,
                )
            )
            sleep(delay)
            continue
        else:
            if circuit_breaker is not None:
                circuit_breaker.record_chunk_success(provider_name)
            return response

    if circuit_breaker is not None:
        circuit_breaker.record_chunk_failure(provider_name)
    if last_error is None:
        raise LLMError(f"provedor '{provider_name}' esgotou as tentativas sem erro explícito")
    raise last_error
