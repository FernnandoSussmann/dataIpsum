"""Testes do executor local (DD-01 §D.3.3, §D.6): mesmos resultados com 1/2/4
workers, `LLMLimiter` entre processos nunca ultrapassa `max_concurrency`, timeout
de `acquire`. Usa processos de verdade (`ProcessPoolExecutor` em modo `spawn`),
por isso as funções de worker precisam estar no nível de módulo (picklable)."""

from __future__ import annotations

import multiprocessing
import time

import pytest

from dataipsum.contracts.executor import ChunkResult, ChunkTask
from dataipsum.contracts.planner import ChunkSpec
from dataipsum.execution.local_executor import (
    LLMAcquireTimeoutError,
    LocalExecutor,
    ProcessLLMLimiter,
)


def _pure_run_chunk(task: ChunkTask) -> ChunkResult:
    return ChunkResult(
        table=task.table,
        chunk_id=task.chunk_spec.id,
        status="done",
        rows=task.chunk_spec.rows,
        sha256=f"sha-{task.chunk_spec.id}-{task.chunk_spec.rows}",
    )


def _tasks(n: int) -> list[ChunkTask]:
    return [
        ChunkTask(
            table="usuarios",
            chunk_spec=ChunkSpec(id=i, first_row=i * 10, rows=10),
            schema=object(),
            root_seed=42,
            sink_options={},
            run_options={},
        )
        for i in range(n)
    ]


@pytest.mark.parametrize("max_workers", [1, 2, 4])
def test_resultados_iguais_com_1_2_4_workers(max_workers: int) -> None:
    executor = LocalExecutor(run_chunk=_pure_run_chunk, max_workers=max_workers)
    try:
        results = sorted(executor.submit(_tasks(8)), key=lambda r: r.chunk_id)
        assert [r.sha256 for r in results] == [f"sha-{i}-10" for i in range(8)]
    finally:
        executor.shutdown(wait=True)


def test_concurrency_e_limitada_a_max_workers() -> None:
    executor = LocalExecutor(run_chunk=_pure_run_chunk, max_workers=4)
    try:
        assert executor.concurrency == 4
        executor.set_concurrency(2)
        assert executor.concurrency == 2
        executor.set_concurrency(99)
        assert executor.concurrency == 4  # nunca passa de max_workers
        executor.set_concurrency(0)
        assert executor.concurrency == 1  # nunca menor que 1
    finally:
        executor.shutdown(wait=True)


def _acquire_and_count(
    task: ChunkTask, limiter: ProcessLLMLimiter, lock: object, active: object, peak: object
) -> ChunkResult:
    with limiter:
        with lock:
            active.value += 1
            if active.value > peak.value:
                peak.value = active.value
        time.sleep(0.05)
        with lock:
            active.value -= 1
    return ChunkResult(
        table=task.table, chunk_id=task.chunk_spec.id, status="done", rows=task.chunk_spec.rows
    )


def test_llm_limiter_nunca_ultrapassa_max_concurrency() -> None:
    import functools

    executor = LocalExecutor(run_chunk=_pure_run_chunk, max_workers=4)
    manager = multiprocessing.Manager()
    try:
        limiter = executor.llm_limiter("local", max_concurrency=2)
        lock = manager.Lock()
        active = manager.Value("i", 0)
        peak = manager.Value("i", 0)
        executor.run_chunk = functools.partial(
            _acquire_and_count, limiter=limiter, lock=lock, active=active, peak=peak
        )
        list(executor.submit(_tasks(8)))
        assert peak.value <= 2
    finally:
        executor.shutdown(wait=True)
        manager.shutdown()


def test_llm_limiter_timeout_de_acquire() -> None:
    manager = multiprocessing.Manager()
    try:
        semaphore = manager.BoundedSemaphore(1)
        semaphore.acquire()
        limiter = ProcessLLMLimiter(semaphore, timeout_seconds=0.2)
        with pytest.raises(LLMAcquireTimeoutError), limiter:
            pass
    finally:
        manager.shutdown()
