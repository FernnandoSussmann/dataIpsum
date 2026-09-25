"""Todo pacote de trilha nasce com um `register(registry)` vazio (DD-00 §3.1)."""

from __future__ import annotations

import importlib

import pytest

from dataipsum.registry import Registry

TRILHA_PACKAGES = (
    "types",
    "relations",
    "llm",
    "execution",
    "sinks",
    "schema_io",
    "cli",
)


@pytest.mark.parametrize("package_name", TRILHA_PACKAGES)
def test_pacote_de_trilha_expoe_register_vazio(package_name: str) -> None:
    module = importlib.import_module(f"dataipsum.{package_name}")
    registry = Registry()
    assert module.register(registry) is None
    assert registry.generators == {}
    assert registry.sinks == {}
