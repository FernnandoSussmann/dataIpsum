"""Todo pacote de trilha expõe `register(registry) -> None` (DD-00 §3.1).

Cada pacote nasce com um `register` vazio; à medida que as trilhas do DD-01/DD-02
são implementadas, ele passa a registrar os geradores/sinks reais. Este teste
verifica só o contrato (`register` existe, é chamável e devolve `None`) e, para os
pacotes ainda não implementados, que o registry continua vazio — o que documenta,
por omissão, quais pacotes já têm implementação real."""

from __future__ import annotations

import importlib

import pytest

from dataipsum.registry import Registry

# Pacotes cujo `register` ainda não popula `registry` (`generators`/`sinks`):
# ou o pacote em si ainda não foi implementado (`execution` não registra nada,
# DD-01 D.1: a trilha D não é dona de geradores/sinks), ou o que ele registra
# fica em outro namespace do registry (`llm` registra `llm_providers`/
# `toxicity`, DD-01 C.4; `sinks`/`schema_io`/`cli` ainda não têm implementação
# própria de registro).
EMPTY_TRILHA_PACKAGES = (
    "llm",
    "execution",
    "sinks",
    "schema_io",
    "cli",
)


@pytest.mark.parametrize("package_name", EMPTY_TRILHA_PACKAGES)
def test_pacote_de_trilha_expoe_register_vazio(package_name: str) -> None:
    module = importlib.import_module(f"dataipsum.{package_name}")
    registry = Registry()
    assert module.register(registry) is None
    assert registry.generators == {}
    assert registry.sinks == {}


def test_types_register_registra_os_17_geradores_e_o_locale_pt_br() -> None:
    import dataipsum.types as types_module

    registry = Registry()
    assert types_module.register(registry) is None
    assert set(registry.generators) == {
        "string",
        "char",
        "int",
        "float",
        "decimal",
        "boolean",
        "date",
        "time",
        "timestamp",
        "uuid",
        "json",
        "array",
        "cpf",
        "rg",
        "cartao_credito",
        "nome_proprio",
        "email",
    }
    assert "pt_BR" in registry.locales
    assert registry.sinks == {}


def test_relations_register_registra_o_gerador_ref() -> None:
    import dataipsum.relations as relations_module

    registry = Registry()
    assert relations_module.register(registry) is None
    assert set(registry.generators) == {"ref"}
    assert registry.sinks == {}
