"""Monitor adaptativo de recursos, AIMD sobre CPU/RAM do sistema (DD-01 §D.3.4).

O `sampler` é injetável, então o algoritmo (`ResourceMonitor.observe`) é puro em
relação ao relógio: ele recebe a amostra e o instante `now` já calculados, e não lê
`time`/`psutil` ele mesmo. O laço "amostra a cada 1s" de verdade (`psutil` + `time`)
fica em `default_sampler`/`MonitorLoop`, usados pelo driver; os testes exercitam só
`ResourceMonitor.observe`.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from dataipsum.errors import ResourceLimitError

CPU_MAX_RANGE = (10.0, 100.0)
MEM_MAX_RANGE = (10.0, 95.0)

OVER_THRESHOLD_STREAK = 2
SLACK_STREAK = 3
SLACK_MARGIN = 10.0
COOLDOWN_SECONDS = 5.0
CRITICAL_MARGIN = 15.0
CRITICAL_ABS_MAX = 95.0
CRITICAL_DURATION_SECONDS = 30.0


@dataclass(frozen=True)
class ResourceSample:
    cpu_percent: float
    mem_percent: float


Sampler = Callable[[], ResourceSample]
Clock = Callable[[], float]


def default_sampler() -> ResourceSample:
    import psutil

    return ResourceSample(
        cpu_percent=psutil.cpu_percent(interval=None), mem_percent=psutil.virtual_memory().percent
    )


def _validate_range(value: float, bounds: tuple[float, float], name: str) -> float:
    lo, hi = bounds
    if not lo <= value <= hi:
        raise ValueError(f"'{name}' deve estar entre {lo} e {hi} (inclusivo), recebido {value}")
    return value


@dataclass
class ResourceMonitor:
    """AIMD sobre CPU/RAM do sistema inteiro (DD-01 §D.3.4). Não vetorizado por
    natureza: é um laço de evento sequencial (uma amostra por vez), então o
    guardrail de "sem `for` com acumulador" do AGENTS.md não se aplica aqui."""

    cpu_max: float = 70.0
    mem_max: float = 60.0
    cpu_count: int = field(default_factory=lambda: os.cpu_count() or 1)
    max_workers: int | None = None
    _effective_max_workers: int = field(init=False, repr=False)
    _concurrency: int = field(init=False, repr=False)
    _paused: bool = field(default=False, init=False, repr=False)
    _over_streak: int = field(default=0, init=False, repr=False)
    _slack_streak: int = field(default=0, init=False, repr=False)
    _cooldown_until: float | None = field(default=None, init=False, repr=False)
    _severe_since: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_range(self.cpu_max, CPU_MAX_RANGE, "cpu_max")
        _validate_range(self.mem_max, MEM_MAX_RANGE, "mem_max")
        self._effective_max_workers = self.max_workers or self.cpu_count
        self._concurrency = max(1, math.floor(self.cpu_count * self.cpu_max / 100))

    @property
    def concurrency(self) -> int:
        return self._concurrency

    @property
    def paused(self) -> bool:
        return self._paused

    def observe(self, sample: ResourceSample, now: float) -> None:
        """Aplica uma amostra ao estado do monitor. Levanta `ResourceLimitError`
        (fatal) quando a RAM passa de 95% por 30s seguidos com concorrência 1."""
        self._update_pause(sample)
        self._update_severe_pressure(sample, now)
        self._update_concurrency(sample, now)

    def _update_pause(self, sample: ResourceSample) -> None:
        pause_threshold = min(CRITICAL_ABS_MAX, self.mem_max + CRITICAL_MARGIN)
        if sample.mem_percent > pause_threshold:
            self._paused = True
        elif self._paused and sample.mem_percent < self.mem_max:
            self._paused = False

    def _update_severe_pressure(self, sample: ResourceSample, now: float) -> None:
        if sample.mem_percent <= CRITICAL_ABS_MAX:
            self._severe_since = None
            return
        if self._severe_since is None:
            self._severe_since = now
            return
        elapsed = now - self._severe_since
        if self._concurrency <= 1 and elapsed >= CRITICAL_DURATION_SECONDS:
            raise ResourceLimitError(
                "RAM acima de 95% por 30s seguidos com concorrência 1. "
                "Reduza 'chunk_size' para diminuir o pico de memória por chunk."
            )

    def _update_concurrency(self, sample: ResourceSample, now: float) -> None:
        over = sample.cpu_percent > self.cpu_max or sample.mem_percent > self.mem_max
        slack = (
            sample.cpu_percent < self.cpu_max - SLACK_MARGIN
            and sample.mem_percent < self.mem_max - SLACK_MARGIN
        )
        if over:
            self._slack_streak = 0
            self._over_streak += 1
            cooldown_active = self._cooldown_until is not None and now < self._cooldown_until
            if self._over_streak >= OVER_THRESHOLD_STREAK and not cooldown_active:
                self._concurrency = max(1, self._concurrency // 2)
                self._cooldown_until = now + COOLDOWN_SECONDS
                self._over_streak = 0
        elif slack:
            self._over_streak = 0
            self._slack_streak += 1
            if self._slack_streak >= SLACK_STREAK:
                self._concurrency = min(self._effective_max_workers, self._concurrency + 1)
                self._slack_streak = 0
        else:
            self._over_streak = 0
            self._slack_streak = 0


@dataclass
class MonitorLoop:
    """Laço de fundo que amostra a cada `interval_seconds` e aplica ao `monitor`.

    O `ResourceLimitError` fatal, se levantado por `monitor.observe`, é capturado e
    exposto em `fatal_error`; o driver confere essa propriedade no laço principal em
    vez de deixar uma thread de fundo derrubar o processo.
    """

    monitor: ResourceMonitor
    sampler: Sampler = default_sampler
    clock: Clock = time.monotonic
    interval_seconds: float = 1.0
    fatal_error: ResourceLimitError | None = field(default=None, init=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="dataipsum-resource-monitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds * 2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.monitor.observe(self.sampler(), self.clock())
            except ResourceLimitError as exc:
                self.fatal_error = exc
                self._stop.set()
                return
            self._stop.wait(self.interval_seconds)
