"""Ordenação topológica de tabelas por nome de dependência (DD-02 §F.3.1, §F.3.4).

Usado tanto pelo export de DDL (ordem de `CREATE TABLE`) quanto pelo import de DDL
(detecção de ciclo entre relações `via`), sem depender do `Planner` da trilha B.
"""

from __future__ import annotations

from collections.abc import Mapping


def topological_order(dependencies: Mapping[str, frozenset[str]]) -> list[str]:
    """Kahn determinístico (ordem alfabética entre nós sem dependência pendente).

    Lança `ValueError` com os nomes restantes quando há um ciclo.
    """
    resolved: set[str] = set()
    remaining = set(dependencies)
    ordered: list[str] = []
    while remaining:
        ready = sorted(name for name in remaining if dependencies[name] <= resolved)
        if not ready:
            raise ValueError(f"{sorted(remaining)}")
        ordered.extend(ready)
        resolved.update(ready)
        remaining.difference_update(ready)
    return ordered
