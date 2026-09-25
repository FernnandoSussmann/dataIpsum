"""Ordem topológica das tabelas do schema (DD-01 §B.3.4, passo 1; §B.4).

Nó = tabela. Aresta `alvo -> tabela`: `tabela` tem uma coluna `ref` apontando
para `alvo`, ou `tabela` é uma tabela `thread` cujos participantes vêm de
`alvo`. Ciclos e auto-referências geram `PlanError` com o caminho do ciclo
(ex.: `"a → b → a"`), conforme DD-01 §B.5 e §B.9.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dataipsum.errors import PlanError

if TYPE_CHECKING:
    from dataipsum.schema.models import Schema


def _participants_table(table: object) -> str | None:
    thread = getattr(table, "thread", None)
    if not isinstance(thread, dict):
        return None
    participants = thread.get("participants")
    if not isinstance(participants, dict):
        return None
    participants_table = participants.get("table")
    return participants_table if isinstance(participants_table, str) else None


def dependencies(schema: Schema) -> dict[str, set[str]]:
    """Mapa `tabela -> {tabelas das quais ela depende}` (precisam vir antes na ordem)."""
    table_names = {table.name for table in schema.tables}
    deps: dict[str, set[str]] = {name: set() for name in table_names}
    for table in schema.tables:
        ref_targets = {
            column.params["table"]
            for column in table.columns
            if column.type == "ref"
            and isinstance(column.params.get("table"), str)
            and column.params["table"] in table_names
        }
        participants_table = _participants_table(table)
        targets = ref_targets | (
            {participants_table} if participants_table in table_names else set()
        )
        self_reference = table.name in targets
        if self_reference:
            raise PlanError(f"auto-referência não é permitida: {table.name} → {table.name}")
        deps[table.name] |= targets
    return deps


def _cycle_path(deps: dict[str, set[str]], start: str) -> list[str]:
    visiting: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            return [*visiting[visiting.index(node) :], node]
        visiting.append(node)
        found = next(
            (result for parent in sorted(deps[node]) if (result := visit(parent)) is not None),
            None,
        )
        if found is None:
            visiting.pop()
        return found

    return visit(start) or [start]


def topological_order(schema: Schema) -> tuple[str, ...]:
    """Ordem topológica (Kahn) das tabelas: pais/alvos antes de filhos/dependentes."""
    deps = dependencies(schema)
    remaining = {name: set(parents) for name, parents in deps.items()}
    order: list[str] = []
    ready = sorted(name for name, parents in remaining.items() if not parents)
    while ready:
        node = ready.pop(0)
        order.append(node)
        del remaining[node]
        for parents in remaining.values():
            parents.discard(node)
        ready = sorted(name for name, parents in remaining.items() if not parents)
    if remaining:
        cycle = _cycle_path(deps, next(iter(sorted(remaining))))
        raise PlanError(f"ciclo entre tabelas: {' → '.join(cycle)}")
    return tuple(order)
