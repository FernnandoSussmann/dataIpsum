"""Trilha B (DD-01): planner de relações e cardinalidades.

`register(registry)` registra o gerador `ref` (DD-01 §B.3.3). O `Planner`
(`RelationsPlanner`) não é armazenado no registry — não há namespace para
isso em `dataipsum.registry.Registry` — e é construído diretamente por quem
monta o `ValidationContext`/motor de execução (DD-00 §3.5).
"""

from __future__ import annotations

from dataipsum.registry import Registry
from dataipsum.relations.planner import RelationsPlanner
from dataipsum.relations.ref import RefGenerator

__all__ = ["RefGenerator", "RelationsPlanner", "register"]


def register(registry: Registry) -> None:
    registry.register_generator("ref", RefGenerator)
