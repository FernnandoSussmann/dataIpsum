"""Executor local, `ProcessPoolExecutor` com contexto `spawn` (DD-01 §D.3.3).

`spawn` evita herdar locks/threads do processo pai (§D.5 item 3). `run_chunk` é a
função picklable executada em cada worker: quem monta o `Executor` real (a
integração S5) passa a função que reconstrói `Planner`/`Registry`/`Sink` a partir do
`ChunkTask` (§D.3.2) — este módulo não assume qual é essa função, só que ela é
picklable e sem estado global, para caber no `ProcessPoolExecutor`.
"""

from __future__ import annotations

import multiprocessing
import os
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from dataipsum.contracts.executor import ChunkResult, ChunkTask

DEFAULT_LLM_ACQUIRE_TIMEOUT_SECONDS = 600.0

RunChunk = Callable[[ChunkTask], ChunkResult]


class LLMAcquireTimeoutError(TimeoutError):
    """`LLMLimiter.acquire` não conseguiu a permissão dentro do timeout (§D.3.3)."""


@dataclass
class ProcessLLMLimiter:
    """`LLMLimiter` entre processos: um `multiprocessing.Manager().BoundedSemaphore`
    por provedor, com timeout de `acquire` (§D.3.3) para nunca travar para sempre."""

    semaphore: Any  # `multiprocessing.managers.AcquirerProxy`; sem stub público em typeshed
    timeout_seconds: float = DEFAULT_LLM_ACQUIRE_TIMEOUT_SECONDS

    def __enter__(self) -> ProcessLLMLimiter:
        acquired = self.semaphore.acquire(timeout=self.timeout_seconds)
        if not acquired:
            raise LLMAcquireTimeoutError(
                f"não foi possível adquirir o LLMLimiter em {self.timeout_seconds}s"
            )
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.semaphore.release()


@dataclass
class LocalExecutor:
    """`Executor` local (DD-00 §3.5) sobre `ProcessPoolExecutor` em modo `spawn`."""

    run_chunk: RunChunk
    max_workers: int = field(default_factory=lambda: os.cpu_count() or 1)
    _concurrency: int = field(init=False, repr=False)
    _pool: ProcessPoolExecutor = field(init=False, repr=False)
    _manager: multiprocessing.managers.SyncManager = field(init=False, repr=False)
    _limiters: dict[str, ProcessLLMLimiter] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._concurrency = self.max_workers
        context = multiprocessing.get_context("spawn")
        self._pool = ProcessPoolExecutor(max_workers=self.max_workers, mp_context=context)
        self._manager = context.Manager()

    def submit(self, tasks: Iterable[ChunkTask]) -> Iterator[ChunkResult]:
        futures = [self._pool.submit(self.run_chunk, task) for task in tasks]
        return (future.result() for future in as_completed(futures))

    def set_concurrency(self, n: int) -> None:
        self._concurrency = max(1, min(n, self.max_workers))

    @property
    def concurrency(self) -> int:
        return self._concurrency

    def shutdown(self, wait: bool) -> None:
        self._pool.shutdown(wait=wait)
        self._manager.shutdown()

    def llm_limiter(self, provider_name: str, max_concurrency: int) -> ProcessLLMLimiter:
        limiter = self._limiters.get(provider_name)
        if limiter is None:
            semaphore = self._manager.BoundedSemaphore(max_concurrency)
            limiter = ProcessLLMLimiter(semaphore)
            self._limiters[provider_name] = limiter
        return limiter
