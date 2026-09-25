"""Testes de `sinks.register` (DD-02, E.4, E.6): sempre registra os sinks de
arquivo; registra os de banco/Kafka só com o extra instalado, e sem ele produz um
erro com instrução de instalação (em vez de "sink desconhecido")."""

from __future__ import annotations

import importlib.util

import pytest

import dataipsum.sinks as sinks_module
from dataipsum.errors import SinkError
from dataipsum.registry import Registry


def test_file_sinks_always_registered() -> None:
    registry = Registry()
    sinks_module.register(registry)

    for name in ("csv", "json", "jsonl", "parquet"):
        assert name in registry.sinks


@pytest.mark.parametrize(
    ("sink_name", "extra_module", "extra_name"),
    [
        ("postgres", "psycopg", "postgres"),
        ("mysql", "pymysql", "mysql"),
        ("kafka", "confluent_kafka", "kafka"),
    ],
)
def test_optional_sink_without_extra_raises_install_hint(
    sink_name: str, extra_module: str, extra_name: str
) -> None:
    assert importlib.util.find_spec(extra_module) is None, (
        f"este teste assume que '{extra_module}' NÃO está instalado no ambiente de dev"
    )
    registry = Registry()
    sinks_module.register(registry)

    sink_class = registry.get_sink(sink_name)
    with pytest.raises(SinkError, match=f"dataipsum\\[{extra_name}\\]"):
        sink_class({})


def test_optional_sink_registered_when_extra_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.machinery
    import sys
    import types

    fake_module = types.ModuleType("psycopg")
    fake_module.__spec__ = importlib.machinery.ModuleSpec("psycopg", loader=None)
    monkeypatch.setitem(sys.modules, "psycopg", fake_module)

    registry = Registry()
    sinks_module.register(registry)

    sink_class = registry.get_sink("postgres")
    assert sink_class.__name__ == "PostgresSink"
