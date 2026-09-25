"""Pacotes de trilha ainda não implementados nascem com um `register(registry)`
vazio (DD-00 §3.1). `sinks` (DD-02, trilha E) já é implementado e registra sinks
de verdade; `cli` (DD-02, trilha G) não é um pacote de generators/sinks e não
expõe `register` (G.4: só `dataipsum.cli:app`).
"""

from __future__ import annotations

import importlib

import pytest

from dataipsum.registry import Registry

EMPTY_TRILHA_PACKAGES = (
    "types",
    "relations",
    "llm",
    "execution",
    "schema_io",
)


@pytest.mark.parametrize("package_name", EMPTY_TRILHA_PACKAGES)
def test_pacote_de_trilha_expoe_register_vazio(package_name: str) -> None:
    module = importlib.import_module(f"dataipsum.{package_name}")
    registry = Registry()
    assert module.register(registry) is None
    assert registry.generators == {}
    assert registry.sinks == {}


def test_sinks_ja_registra_sinks_de_verdade() -> None:
    """DD-02, trilha E: `sinks.register` não é mais um esqueleto vazio."""
    from dataipsum import sinks

    registry = Registry()
    assert sinks.register(registry) is None
    assert set(registry.sinks) == {"csv", "json", "jsonl", "parquet", "postgres", "mysql", "kafka"}


def test_cli_nao_expoe_register() -> None:
    """DD-02, trilha G: a CLI não é um pacote de generators/sinks (G.4)."""
    from dataipsum import cli

    assert not hasattr(cli, "register")
