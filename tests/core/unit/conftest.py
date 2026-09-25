"""Fixtures compartilhadas dos testes unitários do núcleo (DD-00).

Também registra stubs de costura para módulos de outros steps do DD-00 que
podem não existir num worktree isolado (S4 rodou em paralelo com S2 e S3):
`dataipsum.config` (`RunOptions`), `dataipsum.schema.loader` (`load_schema`,
`validate`) e `dataipsum.seeds` (`random_seed`). Depois do merge dos steps,
os módulos reais existem e `_ensure_stub` vira um no-op automaticamente.
"""

from __future__ import annotations

import importlib
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

FULL_EXAMPLE: dict[str, object] = {
    "version": 1,
    "name": "loja",
    "seed": 42,
    "locale": "pt_BR",
    "chunk_size": 10000,
    "limits": {"max_rows_total": 100000000},
    "llm": {
        "default_provider": "local",
        "providers": {
            "local": {
                "kind": "ollama",
                "base_url": "http://ollama:11434",
                "model": "llama3.1:8b",
                "max_concurrency": 2,
                "timeout_s": 120,
                "temperature": 0,
            },
            "nuvem": {
                "kind": "anthropic",
                "model": "modelo-x",
                "api_key_env": "ANTHROPIC_API_KEY",
                "max_concurrency": 4,
            },
        },
        "retry": {"max_attempts": 5, "base_delay_s": 1, "max_delay_s": 60},
    },
    "tables": [
        {
            "name": "usuarios",
            "rows": 1000,
            "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "nome", "type": "nome_proprio", "max_length": 120},
                {"name": "cpf", "type": "cpf", "format": "masked", "invalid_ratio": 0.02},
                {"name": "bio", "type": "string", "max_length": 200, "null_ratio": 0.1},
                {
                    "name": "criado_em",
                    "type": "timestamp",
                    "params": {"min": "2024-01-01T00:00:00Z", "max": "2025-12-31T23:59:59Z"},
                },
            ],
        },
        {
            "name": "produtos",
            "rows": 200,
            "primary_key": {"columns": ["id"], "strategy": "seeded_uuid"},
            "columns": [
                {"name": "id", "type": "uuid"},
                {"name": "titulo", "type": "string", "max_length": 80},
                {
                    "name": "preco",
                    "type": "decimal",
                    "params": {"precision": 10, "scale": 2, "min": "1.00", "max": "5000.00"},
                },
            ],
        },
        {
            "name": "pedidos",
            "primary_key": {"columns": ["id"], "strategy": "sequence"},
            "rows_from": {
                "via": "usuario_id",
                "relation": "one_to_many",
                "cardinality": {"range": {"min": 0, "max": 5}},
            },
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                {
                    "name": "produto_id",
                    "type": "ref",
                    "params": {
                        "table": "produtos",
                        "distribution": {"zipf": {"s": 1.1}},
                    },
                },
                {
                    "name": "comentario",
                    "type": "llm_post",
                    "max_length": 500,
                    "params": {
                        "provider": "local",
                        "prompt": "Escreva um comentário curto sobre o produto.",
                        "mode": "pool",
                        "pool_size": 50,
                        "toxicity": "ratio",
                        "toxicity_ratio": 0.05,
                        "on_failure": "pending",
                    },
                },
            ],
        },
    ],
}


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
