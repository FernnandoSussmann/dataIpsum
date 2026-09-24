"""`RunOptions` e resolução de configuração por precedência (DD-00 §3.8).

Precedência: flags da CLI > variáveis de ambiente `DATAIPSUM_*` > schema > padrões.
O parsing das flags da CLI é da trilha G; `resolve_run_options` recebe os overrides
já extraídos (um `dict`) e faz só a fusão das camadas. O parsing de
`DATAIPSUM_PLUGINS` já vive em `dataipsum.registry.resolve_allowed_plugins`; este
módulo reusa essa função em vez de duplicar a lógica.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from dataipsum.registry import AllowedPlugins, resolve_allowed_plugins
from dataipsum.schema.models import Schema

ExecutorKind = Literal["local", "ray"]
EmitFormat = Literal["ddl", "avro"]

_VALID_EMIT_FORMATS = frozenset({"ddl", "avro"})
_VALID_EXECUTORS = frozenset({"local", "ray"})

MIN_PERCENTAGE = 0.0
MAX_PERCENTAGE = 100.0


@dataclass(frozen=True)
class SinkConfig:
    kind: str
    options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RunOptions:
    """Opções de execução da façade `dataipsum.api` (DD-00 §3.8)."""

    out_dir: Path
    sink: SinkConfig
    seed: int | None = None
    chunk_size: int | None = None
    executor: ExecutorKind = "local"
    cpu_max: float = 70.0
    mem_max: float = 60.0
    max_rows: int | None = None
    llm_on_failure: str | None = None
    emit_schema: tuple[EmitFormat, ...] = ()
    dialect: str | None = None
    allow_plugins: AllowedPlugins = frozenset()
    cache_dir: Path | None = None


def _validate_percentage(value: float, name: str) -> float:
    if not MIN_PERCENTAGE < value <= MAX_PERCENTAGE:
        raise ValueError(
            f"'{name}' deve estar entre {MIN_PERCENTAGE} (exclusivo) e {MAX_PERCENTAGE} "
            f"(inclusivo), recebido {value}"
        )
    return float(value)


def _validate_executor(value: str) -> ExecutorKind:
    if value not in _VALID_EXECUTORS:
        raise ValueError(f"'executor' inválido: '{value}'. Aceitos: {sorted(_VALID_EXECUTORS)}")
    return cast(ExecutorKind, value)


def _validate_emit_schema(values: tuple[str, ...]) -> tuple[EmitFormat, ...]:
    invalid = sorted({value for value in values if value not in _VALID_EMIT_FORMATS})
    if invalid:
        raise ValueError(
            f"'emit_schema' inválido: {invalid}. Aceitos: {sorted(_VALID_EMIT_FORMATS)}"
        )
    return cast(tuple[EmitFormat, ...], tuple(values))


# Variáveis `DATAIPSUM_*` lidas aqui (cpu/mem/executor/etc.); `DATAIPSUM_PLUGINS` é
# lida à parte, via `resolve_allowed_plugins` (não duplicamos o parsing dela).
_ENV_VAR_PARSERS: dict[str, tuple[str, Callable[[str], object]]] = {
    "out_dir": ("DATAIPSUM_OUT_DIR", Path),
    "seed": ("DATAIPSUM_SEED", int),
    "chunk_size": ("DATAIPSUM_CHUNK_SIZE", int),
    "executor": ("DATAIPSUM_EXECUTOR", _validate_executor),
    "cpu_max": ("DATAIPSUM_CPU_MAX", float),
    "mem_max": ("DATAIPSUM_MEM_MAX", float),
    "max_rows": ("DATAIPSUM_MAX_ROWS", int),
    "llm_on_failure": ("DATAIPSUM_LLM_ON_FAILURE", str),
    "dialect": ("DATAIPSUM_DIALECT", str),
    "cache_dir": ("DATAIPSUM_CACHE_DIR", Path),
}


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _read_env_overrides(env: Mapping[str, str]) -> dict[str, object]:
    scalar = {
        field_name: parser(env[var_name])
        for field_name, (var_name, parser) in _ENV_VAR_PARSERS.items()
        if env.get(var_name)
    }
    if env.get("DATAIPSUM_EMIT_SCHEMA"):
        scalar["emit_schema"] = _split_csv(env["DATAIPSUM_EMIT_SCHEMA"])
    return scalar


def _from_schema(schema: Schema) -> dict[str, object]:
    return {
        key: value
        for key, value in {"seed": schema.seed, "chunk_size": schema.chunk_size}.items()
        if value is not None
    }


def _resolve_field[T](name: str, layers: tuple[Mapping[str, object], ...], default: T) -> T:
    for layer in layers:
        value = layer.get(name)
        if value is not None:
            return cast(T, value)
    return default


def _resolve_cache_dir(
    layers: tuple[Mapping[str, object], ...], default: Path | None
) -> Path | None:
    value = _resolve_field("cache_dir", layers, default)
    return None if value is None else Path(value)


def resolve_run_options(
    cli_overrides: Mapping[str, object],
    env: Mapping[str, str],
    schema: Schema,
    defaults: RunOptions,
) -> RunOptions:
    """Funde CLI, env `DATAIPSUM_*`, schema e padrões, nessa ordem de precedência."""
    layers = (cli_overrides, _read_env_overrides(env), _from_schema(schema))
    no_plugins = bool(cli_overrides.get("no_plugins", False))
    allow_plugins = resolve_allowed_plugins(env.get("DATAIPSUM_PLUGINS"), no_plugins=no_plugins)

    return RunOptions(
        out_dir=Path(_resolve_field("out_dir", layers, defaults.out_dir)),
        sink=_resolve_field("sink", layers, defaults.sink),
        seed=_resolve_field("seed", layers, defaults.seed),
        chunk_size=_resolve_field("chunk_size", layers, defaults.chunk_size),
        executor=_validate_executor(_resolve_field("executor", layers, defaults.executor)),
        cpu_max=_validate_percentage(
            float(_resolve_field("cpu_max", layers, defaults.cpu_max)), "cpu_max"
        ),
        mem_max=_validate_percentage(
            float(_resolve_field("mem_max", layers, defaults.mem_max)), "mem_max"
        ),
        max_rows=_resolve_field("max_rows", layers, defaults.max_rows),
        llm_on_failure=_resolve_field("llm_on_failure", layers, defaults.llm_on_failure),
        emit_schema=_validate_emit_schema(
            tuple(_resolve_field("emit_schema", layers, defaults.emit_schema))
        ),
        dialect=_resolve_field("dialect", layers, defaults.dialect),
        allow_plugins=allow_plugins,
        cache_dir=_resolve_cache_dir(layers, defaults.cache_dir),
    )
