"""Testes de `RunOptions` e da resolução de configuração (DD-00 §7.1: config.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataipsum.config import RunOptions, SinkConfig, resolve_run_options
from dataipsum.schema.loader import load_schema

DEFAULTS = RunOptions(out_dir=Path("./out"), sink=SinkConfig(kind="parquet"))


def _schema(**overrides: object) -> object:
    doc: dict[str, object] = {
        "version": 1,
        "tables": [
            {
                "name": "t",
                "rows": 10,
                "primary_key": {"columns": ["id"], "strategy": "sequence"},
                "columns": [{"name": "id", "type": "int"}],
            }
        ],
    }
    doc.update(overrides)
    return load_schema(doc)


# --- precedência --------------------------------------------------------


def test_sem_overrides_usa_padroes() -> None:
    options = resolve_run_options({}, {}, _schema(), DEFAULTS)
    assert options.cpu_max == 70.0
    assert options.mem_max == 60.0
    assert options.executor == "local"
    assert options.seed is None


def test_schema_sobrepoe_padrao() -> None:
    options = resolve_run_options({}, {}, _schema(seed=7, chunk_size=500), DEFAULTS)
    assert options.seed == 7
    assert options.chunk_size == 500


def test_env_sobrepoe_schema() -> None:
    options = resolve_run_options({}, {"DATAIPSUM_SEED": "99"}, _schema(seed=7), DEFAULTS)
    assert options.seed == 99


def test_cli_sobrepoe_env() -> None:
    options = resolve_run_options({"seed": 1}, {"DATAIPSUM_SEED": "99"}, _schema(seed=7), DEFAULTS)
    assert options.seed == 1


def test_cli_sobrepoe_env_sobrepoe_schema_sobrepoe_padrao_em_cadeia_completa() -> None:
    schema = _schema(seed=7, chunk_size=500)
    only_defaults = resolve_run_options({}, {}, schema, DEFAULTS)
    assert only_defaults.chunk_size == 500  # schema > padrão

    with_env = resolve_run_options({}, {"DATAIPSUM_CHUNK_SIZE": "800"}, schema, DEFAULTS)
    assert with_env.chunk_size == 800  # env > schema

    with_cli = resolve_run_options(
        {"chunk_size": 999}, {"DATAIPSUM_CHUNK_SIZE": "800"}, schema, DEFAULTS
    )
    assert with_cli.chunk_size == 999  # cli > env


def test_out_dir_e_sink_resolvidos_da_cli() -> None:
    options = resolve_run_options(
        {"out_dir": Path("/tmp/saida"), "sink": SinkConfig(kind="csv")}, {}, _schema(), DEFAULTS
    )
    assert options.out_dir == Path("/tmp/saida")
    assert options.sink.kind == "csv"


def test_emit_schema_via_env_csv() -> None:
    options = resolve_run_options({}, {"DATAIPSUM_EMIT_SCHEMA": "ddl, avro"}, _schema(), DEFAULTS)
    assert options.emit_schema == ("ddl", "avro")


def test_emit_schema_invalido_gera_erro() -> None:
    with pytest.raises(ValueError, match="emit_schema"):
        resolve_run_options({"emit_schema": ["xml"]}, {}, _schema(), DEFAULTS)


# --- faixas de cpu_max / mem_max -----------------------------------------


@pytest.mark.parametrize("value", [0, -1, 101, 1000])
def test_cpu_max_fora_da_faixa_gera_erro(value: float) -> None:
    with pytest.raises(ValueError, match="cpu_max"):
        resolve_run_options({"cpu_max": value}, {}, _schema(), DEFAULTS)


@pytest.mark.parametrize("value", [0, -1, 101])
def test_mem_max_fora_da_faixa_gera_erro(value: float) -> None:
    with pytest.raises(ValueError, match="mem_max"):
        resolve_run_options({"mem_max": value}, {}, _schema(), DEFAULTS)


def test_cpu_max_e_mem_max_no_limite_sao_aceitos() -> None:
    options = resolve_run_options({"cpu_max": 100, "mem_max": 100}, {}, _schema(), DEFAULTS)
    assert options.cpu_max == 100.0
    assert options.mem_max == 100.0


def test_executor_invalido_gera_erro() -> None:
    with pytest.raises(ValueError, match="executor"):
        resolve_run_options({"executor": "kubernetes"}, {}, _schema(), DEFAULTS)


def test_executor_ray_valido() -> None:
    options = resolve_run_options({"executor": "ray"}, {}, _schema(), DEFAULTS)
    assert options.executor == "ray"


# --- DATAIPSUM_PLUGINS (reusa dataipsum.registry, não duplica o parsing) --


def test_allow_plugins_sem_env_e_vazio() -> None:
    options = resolve_run_options({}, {}, _schema(), DEFAULTS)
    assert options.allow_plugins == frozenset()


def test_allow_plugins_com_env() -> None:
    options = resolve_run_options(
        {}, {"DATAIPSUM_PLUGINS": "meu-plugin, outro"}, _schema(), DEFAULTS
    )
    assert options.allow_plugins == frozenset({"meu-plugin", "outro"})


def test_allow_plugins_asterisco() -> None:
    options = resolve_run_options({}, {"DATAIPSUM_PLUGINS": "*"}, _schema(), DEFAULTS)
    assert options.allow_plugins == "*"


def test_no_plugins_da_cli_sobrepoe_env() -> None:
    options = resolve_run_options(
        {"no_plugins": True}, {"DATAIPSUM_PLUGINS": "*"}, _schema(), DEFAULTS
    )
    assert options.allow_plugins == frozenset()


# --- outros campos ---------------------------------------------------------


def test_cache_dir_none_por_padrao() -> None:
    options = resolve_run_options({}, {}, _schema(), DEFAULTS)
    assert options.cache_dir is None


def test_cache_dir_via_env() -> None:
    options = resolve_run_options({}, {"DATAIPSUM_CACHE_DIR": "/tmp/cache"}, _schema(), DEFAULTS)
    assert options.cache_dir == Path("/tmp/cache")


def test_max_rows_e_dialect_e_llm_on_failure() -> None:
    options = resolve_run_options(
        {"max_rows": 500, "dialect": "postgres", "llm_on_failure": "placeholder"},
        {},
        _schema(),
        DEFAULTS,
    )
    assert options.max_rows == 500
    assert options.dialect == "postgres"
    assert options.llm_on_failure == "placeholder"


def test_run_options_e_imutavel() -> None:
    options = resolve_run_options({}, {}, _schema(), DEFAULTS)
    with pytest.raises(AttributeError):
        options.cpu_max = 10  # type: ignore[misc]
