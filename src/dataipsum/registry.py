"""Registry único de geradores, sinks e sub-registries; carga de plugins (DD-00 §3.4)."""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
from dataclasses import dataclass, field
from typing import Literal, cast

from dataipsum.errors import RegistryConflictError

logger = logging.getLogger("dataipsum.registry")

# Ordem fixa de carga dos built-ins (§3.4).
_BUILTIN_PACKAGES = ("types", "relations", "llm", "sinks")

_GENERATOR_ENTRY_POINT_GROUP = "dataipsum.generators"
_SINK_ENTRY_POINT_GROUP = "dataipsum.sinks"

BUILTIN_ORIGIN = "builtin"

AllowedPlugins = frozenset[str] | Literal["*"]


@dataclass(frozen=True)
class PluginRecord:
    name: str
    version: str
    origin: str
    namespace: str


@dataclass
class Registry:
    """Registry com os namespaces `generators`, `sinks`, `locales`, `llm_providers` e `toxicity`."""

    generators: dict[str, object] = field(default_factory=dict)
    sinks: dict[str, object] = field(default_factory=dict)
    locales: dict[str, object] = field(default_factory=dict)
    llm_providers: dict[str, object] = field(default_factory=dict)
    toxicity: dict[str, object] = field(default_factory=dict)
    loaded_plugins: list[PluginRecord] = field(default_factory=list)
    _origins: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)

    def _namespace(self, name: str) -> dict[str, object]:
        return cast(dict[str, object], getattr(self, name))

    def register(
        self, namespace: str, name: str, value: object, *, origin: str = BUILTIN_ORIGIN
    ) -> None:
        target = self._namespace(namespace)
        key = (namespace, name)
        existing_origin = self._origins.get(key)
        if existing_origin is not None:
            if existing_origin == BUILTIN_ORIGIN or origin == BUILTIN_ORIGIN:
                raise RegistryConflictError(
                    f"'{name}' em '{namespace}' já está registrado como built-in"
                )
            raise RegistryConflictError(
                f"'{name}' em '{namespace}' já foi registrado pelo plugin '{existing_origin}'"
            )
        target[name] = value
        self._origins[key] = origin

    def register_generator(self, name: str, cls: type, *, origin: str = BUILTIN_ORIGIN) -> None:
        self.register("generators", name, cls, origin=origin)

    def register_sink(self, name: str, cls: type, *, origin: str = BUILTIN_ORIGIN) -> None:
        self.register("sinks", name, cls, origin=origin)

    def register_locale(self, name: str, value: object, *, origin: str = BUILTIN_ORIGIN) -> None:
        self.register("locales", name, value, origin=origin)

    def register_llm_provider(self, name: str, cls: type, *, origin: str = BUILTIN_ORIGIN) -> None:
        self.register("llm_providers", name, cls, origin=origin)

    def register_toxicity(self, name: str, cls: type, *, origin: str = BUILTIN_ORIGIN) -> None:
        self.register("toxicity", name, cls, origin=origin)

    def get_generator(self, name: str) -> type:
        return _get_or_raise(self.generators, name, "gerador")

    def get_sink(self, name: str) -> type:
        return _get_or_raise(self.sinks, name, "sink")


def _get_or_raise(namespace: dict[str, object], name: str, label: str) -> type:
    try:
        return cast(type, namespace[name])
    except KeyError:
        known = ", ".join(sorted(namespace)) or "nenhum"
        raise KeyError(f"{label} desconhecido: '{name}'. Registrados: {known}") from None


def resolve_allowed_plugins(env_value: str | None, *, no_plugins: bool) -> AllowedPlugins:
    """`DATAIPSUM_PLUGINS` (allowlist) sobreposta por `--no-plugins` (§3.4)."""
    if no_plugins:
        return frozenset()
    if env_value is None:
        return frozenset()
    if env_value.strip() == "*":
        return "*"
    return frozenset(name.strip() for name in env_value.split(",") if name.strip())


def register_builtins(registry: Registry) -> None:
    for package_name in _BUILTIN_PACKAGES:
        module = importlib.import_module(f"dataipsum.{package_name}")
        module.register(registry)


def load_plugins(registry: Registry, *, allowed: AllowedPlugins) -> None:
    for group, namespace in (
        (_GENERATOR_ENTRY_POINT_GROUP, "generators"),
        (_SINK_ENTRY_POINT_GROUP, "sinks"),
    ):
        for entry_point in importlib.metadata.entry_points(group=group):
            _load_entry_point(registry, entry_point, namespace, allowed)


def _load_entry_point(
    registry: Registry,
    entry_point: importlib.metadata.EntryPoint,
    namespace: str,
    allowed: AllowedPlugins,
) -> None:
    dist_name = entry_point.dist.name if entry_point.dist is not None else "desconhecido"
    if allowed != "*" and dist_name not in allowed:
        logger.warning(
            "Plugin '%s' (distribuição '%s') não carregado: defina DATAIPSUM_PLUGINS=%s "
            "para autorizá-lo (ou DATAIPSUM_PLUGINS=* para todos).",
            entry_point.name,
            dist_name,
            dist_name,
        )
        return
    value = entry_point.load()
    registry.register(namespace, entry_point.name, value, origin=dist_name)
    version = entry_point.dist.version if entry_point.dist is not None else "desconhecida"
    record = PluginRecord(
        name=entry_point.name, version=version, origin=dist_name, namespace=namespace
    )
    registry.loaded_plugins.append(record)
    logger.info("Plugin carregado: %s v%s (origem: %s)", record.name, record.version, record.origin)


def build_registry(*, allow_plugins_env: str | None = None, no_plugins: bool = False) -> Registry:
    registry = Registry()
    register_builtins(registry)
    allowed = resolve_allowed_plugins(allow_plugins_env, no_plugins=no_plugins)
    load_plugins(registry, allowed=allowed)
    return registry
