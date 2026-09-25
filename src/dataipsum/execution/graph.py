"""Grafo de dependências entre tabelas (DD-01 §D.3.1).

O grafo é o mesmo usado pela ordem topológica da trilha B: uma aresta
pai -> filha para cada coluna `ref` (`params.table`) e para os participantes
de uma tabela `thread` (`thread.participants`, lista de nomes de tabela). A
trilha D deriva esse grafo diretamente do `Schema`, sem depender do
`Planner` (cujo contrato não expõe as arestas), para poder agendar tabelas
independentes em paralelo e travar tabelas filhas até que as tabelas das
quais dependem terminem.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dataipsum.schema.models import Schema, TableSpec

REF_COLUMN_TYPE = "ref"


def _thread_participants(table: TableSpec) -> frozenset[str]:
    if table.thread is None:
        return frozenset()
    participants = table.thread.get("participants")
    if not isinstance(participants, list):
        return frozenset()
    return frozenset(name for name in participants if isinstance(name, str))


def _table_dependencies(table: TableSpec, table_names: frozenset[str]) -> frozenset[str]:
    ref_parents = frozenset(
        parent
        for column in table.columns
        if column.type == REF_COLUMN_TYPE
        for parent in (column.params.get("table"),)
        if isinstance(parent, str) and parent in table_names
    )
    return ref_parents | (_thread_participants(table) & table_names)


def dependency_graph(schema: Schema) -> dict[str, frozenset[str]]:
    """Mapa `tabela -> tabelas das quais ela depende (pais)`."""
    table_names = frozenset(table.name for table in schema.tables)
    return {table.name: _table_dependencies(table, table_names) for table in schema.tables}


def has_cycle(graph: Mapping[str, frozenset[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited or node not in graph:
            return False
        visiting.add(node)
        found = any(visit(dep) for dep in graph[node])
        visiting.discard(node)
        visited.add(node)
        return found

    return any(visit(node) for node in graph)


def root_tables(graph: Mapping[str, frozenset[str]]) -> frozenset[str]:
    return frozenset(name for name, deps in graph.items() if not deps)


def ready_tables(graph: Mapping[str, frozenset[str]], resolved: frozenset[str]) -> frozenset[str]:
    """Tabelas cujos pais já terminaram, mas que ainda não estão em `resolved`."""
    return frozenset(name for name, deps in graph.items() if deps <= resolved) - resolved
