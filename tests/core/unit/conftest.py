"""Costura de teste para contratos de outros steps do DD-00 que ainda não
existem neste worktree (S4 roda em paralelo com S2 e S3):

- `dataipsum.config` (`RunOptions`) e `dataipsum.schema.loader`
  (`load_schema`, `validate`) — S2;
- `dataipsum.seeds` (`random_seed`) — S3.

`dataipsum.api` importa esses três módulos por nome, como o contrato entre
steps do DD-00 exige (ver o docstring de `dataipsum/api.py`). Este arquivo
registra um stub mínimo em `sys.modules` **só quando o módulo real não pode
ser importado** — depois do merge dos outros steps, `importlib.import_module`
passa a ter sucesso e nada aqui é registrado, então este conftest vira um
no-op automaticamente e não precisa ser removido.

Os testes de `dataipsum.api` não dependem do comportamento desses stubs: eles
substituem os pontos de costura reais (`dataipsum.api._load_schema` e
`dataipsum.api._validate`) via `unittest.mock.patch` a cada teste.
"""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


def _ensure_stub(module_name: str, build_stub: Callable[[], types.ModuleType]) -> None:
    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError:
        sys.modules[module_name] = build_stub()


def _build_config_stub() -> types.ModuleType:
    module = types.ModuleType("dataipsum.config")

    @dataclass
    class RunOptions:
        """Stub de `dataipsum.config.RunOptions` (S2, DD-00 §3.8) para testes do S4."""

        out_dir: Path
        sink: dict[str, object] = field(default_factory=dict)
        seed: int | None = None
        chunk_size: int | None = None
        executor: Literal["local", "ray"] = "local"
        cpu_max: int = 70
        mem_max: int = 60
        max_rows: int | None = None
        llm_on_failure: str | None = None
        emit_schema: list[str] = field(default_factory=list)
        dialect: str | None = None
        allow_plugins: bool = False
        cache_dir: Path | None = None

    module.RunOptions = RunOptions  # type: ignore[attr-defined]
    return module


def _build_schema_package_stub() -> types.ModuleType:
    return types.ModuleType("dataipsum.schema")


def _build_schema_loader_stub() -> types.ModuleType:
    module = types.ModuleType("dataipsum.schema.loader")

    def load_schema(source: Path | str | dict[str, object]) -> object:
        raise NotImplementedError("stub de dataipsum.schema.loader.load_schema (S2)")

    def validate(schema: object, ctx: object | None = None) -> object:
        raise NotImplementedError("stub de dataipsum.schema.loader.validate (S2)")

    module.load_schema = load_schema  # type: ignore[attr-defined]
    module.validate = validate  # type: ignore[attr-defined]
    return module


def _build_seeds_stub() -> types.ModuleType:
    module = types.ModuleType("dataipsum.seeds")

    def random_seed() -> int:
        raise NotImplementedError("stub de dataipsum.seeds.random_seed (S3)")

    module.random_seed = random_seed  # type: ignore[attr-defined]
    return module


_ensure_stub("dataipsum.config", _build_config_stub)
_ensure_stub("dataipsum.schema", _build_schema_package_stub)
_ensure_stub("dataipsum.schema.loader", _build_schema_loader_stub)
_ensure_stub("dataipsum.seeds", _build_seeds_stub)
