"""Testes do registry (DD-00 §7.1: registry.py)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dataipsum.errors import RegistryConflictError
from dataipsum.registry import (
    Registry,
    build_registry,
    load_plugins,
    register_builtins,
    resolve_allowed_plugins,
)


class FakeGenerator:
    name = "fake"


def make_entry_point(
    name: str, dist_name: str, dist_version: str = "1.0.0", value: object = FakeGenerator
):
    return SimpleNamespace(
        name=name,
        dist=SimpleNamespace(name=dist_name, version=dist_version),
        load=lambda: value,
    )


def test_registra_e_obtem_built_in() -> None:
    registry = Registry()
    registry.register_generator("cpf", FakeGenerator)
    assert registry.get_generator("cpf") is FakeGenerator


def test_registra_e_obtem_sink() -> None:
    registry = Registry()
    registry.register_sink("parquet", FakeGenerator)
    assert registry.get_sink("parquet") is FakeGenerator


def test_registra_locale_e_llm_provider_e_toxicity() -> None:
    registry = Registry()
    registry.register_locale("pt_BR", {"lang": "pt"})
    registry.register_llm_provider("ollama", FakeGenerator)
    registry.register_toxicity("detoxify", FakeGenerator)
    assert registry.locales["pt_BR"] == {"lang": "pt"}
    assert registry.llm_providers["ollama"] is FakeGenerator
    assert registry.toxicity["detoxify"] is FakeGenerator


def test_nome_desconhecido_gera_erro_com_sugestao() -> None:
    registry = Registry()
    registry.register_generator("cpf", FakeGenerator)
    with pytest.raises(KeyError, match="cpf"):
        registry.get_generator("cnpj")


def test_register_builtins_chama_register_dos_pacotes_em_ordem() -> None:
    registry = Registry()
    register_builtins(registry)
    assert registry.generators == {}
    assert set(registry.sinks) == {"csv", "json", "jsonl", "parquet", "postgres", "mysql", "kafka"}


def test_resolve_allowed_plugins_sem_env_nao_libera_nada() -> None:
    assert resolve_allowed_plugins(None, no_plugins=False) == frozenset()


def test_resolve_allowed_plugins_com_lista() -> None:
    assert resolve_allowed_plugins("a, b", no_plugins=False) == frozenset({"a", "b"})


def test_resolve_allowed_plugins_com_asterisco_libera_tudo() -> None:
    assert resolve_allowed_plugins("*", no_plugins=False) == "*"


def test_no_plugins_sobrepoe_a_env() -> None:
    assert resolve_allowed_plugins("*", no_plugins=True) == frozenset()


def test_plugin_sem_allowlist_e_ignorado_e_avisado(caplog: pytest.LogCaptureFixture) -> None:
    registry = Registry()
    entry_point = make_entry_point("cnpj", "meu-plugin")
    with (
        patch("dataipsum.registry.importlib.metadata.entry_points", return_value=[entry_point]),
        caplog.at_level("WARNING", logger="dataipsum.registry"),
    ):
        load_plugins(registry, allowed=frozenset())
    assert "cnpj" not in registry.generators
    assert "DATAIPSUM_PLUGINS" in caplog.text


def test_plugin_na_allowlist_e_carregado() -> None:
    registry = Registry()
    entry_point = make_entry_point("cnpj", "meu-plugin")
    with patch("dataipsum.registry.importlib.metadata.entry_points", return_value=[entry_point]):
        load_plugins(registry, allowed=frozenset({"meu-plugin"}))
    assert registry.generators["cnpj"] is FakeGenerator
    assert registry.loaded_plugins[0].name == "cnpj"
    assert registry.loaded_plugins[0].origin == "meu-plugin"


def test_asterisco_libera_todos_os_plugins() -> None:
    registry = Registry()
    entry_point = make_entry_point("cnpj", "qualquer-plugin")
    with patch("dataipsum.registry.importlib.metadata.entry_points", return_value=[entry_point]):
        load_plugins(registry, allowed="*")
    assert registry.generators["cnpj"] is FakeGenerator


def test_plugin_nao_pode_sobrescrever_built_in() -> None:
    registry = Registry()
    registry.register_generator("cpf", FakeGenerator, origin="builtin")
    entry_point = make_entry_point("cpf", "meu-plugin")
    with (
        patch("dataipsum.registry.importlib.metadata.entry_points", return_value=[entry_point]),
        pytest.raises(RegistryConflictError),
    ):
        load_plugins(registry, allowed="*")


def test_dois_plugins_com_mesmo_nome_geram_erro() -> None:
    registry = Registry()
    entry_point_a = make_entry_point("cnpj", "plugin-a")
    entry_point_b = make_entry_point("cnpj", "plugin-b")
    with (
        patch(
            "dataipsum.registry.importlib.metadata.entry_points",
            return_value=[entry_point_a, entry_point_b],
        ),
        pytest.raises(RegistryConflictError),
    ):
        load_plugins(registry, allowed="*")


def test_build_registry_sem_plugins_por_padrao() -> None:
    entry_point = make_entry_point("cnpj", "meu-plugin")
    with patch("dataipsum.registry.importlib.metadata.entry_points", return_value=[entry_point]):
        registry = build_registry()
    assert "cnpj" not in registry.generators


def test_build_registry_com_env(monkeypatch: pytest.MonkeyPatch) -> None:
    entry_point = make_entry_point("cnpj", "meu-plugin")
    with patch("dataipsum.registry.importlib.metadata.entry_points", return_value=[entry_point]):
        registry = build_registry(allow_plugins_env="meu-plugin")
    assert registry.generators["cnpj"] is FakeGenerator


def test_build_registry_com_no_plugins_sobrepoe_env() -> None:
    entry_point = make_entry_point("cnpj", "meu-plugin")
    with patch("dataipsum.registry.importlib.metadata.entry_points", return_value=[entry_point]):
        registry = build_registry(allow_plugins_env="*", no_plugins=True)
    assert "cnpj" not in registry.generators
