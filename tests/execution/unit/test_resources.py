"""Testes do monitor adaptativo de recursos (DD-01 §D.3.4, §D.6)."""

from __future__ import annotations

import pytest

from dataipsum.errors import ResourceLimitError
from dataipsum.execution.resources import ResourceMonitor, ResourceSample


def test_concorrencia_inicial_e_derivada_de_cpu_max() -> None:
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=8)
    assert monitor.concurrency == 5  # floor(8 * 70 / 100)


def test_faixas_de_cpu_max_e_mem_max_sao_validadas() -> None:
    with pytest.raises(ValueError, match="cpu_max"):
        ResourceMonitor(cpu_max=5.0, mem_max=60.0)
    with pytest.raises(ValueError, match="mem_max"):
        ResourceMonitor(cpu_max=70.0, mem_max=96.0)


def test_reducao_multiplicativa_apos_duas_amostras_acima_do_teto() -> None:
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=8)
    assert monitor.concurrency == 5
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=0.0)
    assert monitor.concurrency == 5  # só reduz na 2ª amostra seguida
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=1.0)
    assert monitor.concurrency == 2  # max(1, 5 // 2)


def test_cooldown_impede_nova_reducao_por_5s() -> None:
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=8)
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=0.0)
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=1.0)
    assert monitor.concurrency == 2
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=2.0)
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=3.0)
    assert monitor.concurrency == 2  # ainda em cooldown (< 5s desde a última redução)
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=6.0)
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=7.0)
    assert monitor.concurrency == 1  # cooldown expirou, reduz de novo


def test_aumento_aditivo_apos_tres_amostras_de_folga() -> None:
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=8)
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=0.0)
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=1.0)
    assert monitor.concurrency == 2
    for now in (10.0, 11.0):
        monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=10.0), now=now)
    assert monitor.concurrency == 2  # só na 3ª amostra de folga seguida
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=10.0), now=12.0)
    assert monitor.concurrency == 3


def test_aumento_nunca_passa_de_max_workers() -> None:
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=2, max_workers=2)
    for now in range(10):
        monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=10.0), now=float(now))
    assert monitor.concurrency == 2


def test_pausa_por_pressao_critica_de_memoria() -> None:
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=8)
    assert monitor.paused is False
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=80.0), now=0.0)
    assert monitor.paused is True
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=50.0), now=1.0)
    assert monitor.paused is False


def test_erro_fatal_apos_30s_com_ram_acima_de_95_e_concorrencia_1() -> None:
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=1)
    assert monitor.concurrency == 1
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=96.0), now=0.0)
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=96.0), now=20.0)
    with pytest.raises(ResourceLimitError, match="chunk_size"):
        monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=96.0), now=31.0)


def test_sem_erro_fatal_se_ram_volta_a_ficar_normal_antes_de_30s() -> None:
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=1)
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=96.0), now=0.0)
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=50.0), now=10.0)
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=96.0), now=11.0)
    monitor.observe(
        ResourceSample(cpu_percent=10.0, mem_percent=96.0), now=31.0
    )  # só 20s desde now=11


def test_transicoes_sao_logadas_em_info(caplog: pytest.LogCaptureFixture) -> None:
    """DD-01 §D.3.4: "As transições são logadas (nível INFO)"."""
    caplog.set_level("INFO", logger="dataipsum.execution.resources")
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=8)

    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=0.0)
    monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=1.0)
    assert any("reduzindo concorrência" in r.message for r in caplog.records)

    caplog.clear()
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=90.0), now=2.0)
    assert any("pausando submissão" in r.message for r in caplog.records)
    assert monitor.paused is True

    caplog.clear()
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=10.0), now=3.0)
    assert any("retomando submissão" in r.message for r in caplog.records)
    assert monitor.paused is False

    caplog.clear()
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=10.0), now=4.0)
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=10.0), now=5.0)
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=10.0), now=6.0)
    assert any("aumentando concorrência" in r.message for r in caplog.records)


def test_erro_fatal_e_logado_em_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="dataipsum.execution.resources")
    monitor = ResourceMonitor(cpu_max=70.0, mem_max=60.0, cpu_count=1)
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=96.0), now=0.0)
    monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=96.0), now=20.0)
    with pytest.raises(ResourceLimitError):
        monitor.observe(ResourceSample(cpu_percent=10.0, mem_percent=96.0), now=31.0)
    assert any(r.levelname == "ERROR" for r in caplog.records)
