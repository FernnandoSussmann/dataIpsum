"""Testes do executor Ray que não precisam de um cluster de verdade (DD-01 §D.3.6,
M2): a mensagem de erro quando `ray` não está instalado (extra `[ray]` ausente) e o
aviso de endereço público (§D.5 item 6). Os testes que precisam de um cluster Ray
real ficam marcados `ray` e não rodam aqui (ver `tests/docker/test_image_execucao.py`)."""

from __future__ import annotations

import logging

import pytest

from dataipsum.errors import ExecutorError
from dataipsum.execution.ray_executor import RayExecutor, warn_if_public_ray_address


def _run_chunk(task: object) -> object:  # pragma: no cover -- nunca chamado sem ray
    raise AssertionError("não deveria ser chamado")


def test_sem_ray_instalado_levanta_executor_error_com_mensagem_clara() -> None:
    try:
        import ray  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("ray está instalado neste ambiente; este teste cobre a ausência dele")

    with pytest.raises(ExecutorError, match=r"\[ray\]"):
        RayExecutor(ray_address="auto", run_chunk=_run_chunk)


def test_warn_if_public_ray_address_nao_avisa_para_auto(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="dataipsum.execution.ray"):
        warn_if_public_ray_address("auto")
    assert caplog.records == []


def test_warn_if_public_ray_address_nao_avisa_para_ip_privado(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="dataipsum.execution.ray"):
        warn_if_public_ray_address("ray://10.0.0.5:10001")
    assert caplog.records == []


def test_warn_if_public_ray_address_avisa_para_ip_publico(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="dataipsum.execution.ray"):
        warn_if_public_ray_address("ray://8.8.8.8:10001")
    assert any("público" in record.message for record in caplog.records)
