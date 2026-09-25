"""Testes do grafo de dependências entre tabelas (DD-01 §D.3.1, §D.6)."""

from __future__ import annotations

from dataipsum.execution.graph import dependency_graph, has_cycle, ready_tables, root_tables
from dataipsum.schema.loader import load_schema


def _schema_dict() -> dict[str, object]:
    return {
        "version": 1,
        "name": "loja",
        "seed": 42,
        "tables": [
            {
                "name": "usuarios",
                "rows": 10,
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "columns": [{"name": "id", "type": "int"}],
            },
            {
                "name": "produtos",
                "rows": 5,
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "columns": [{"name": "id", "type": "int"}],
            },
            {
                "name": "pedidos",
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "rows_from": {"via": "usuario_id", "relation": "one_to_many"},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                    {"name": "produto_id", "type": "ref", "params": {"table": "produtos"}},
                ],
            },
        ],
    }


def test_dependency_graph_tem_uma_aresta_por_coluna_ref() -> None:
    schema = load_schema(_schema_dict())
    graph = dependency_graph(schema)
    assert graph["usuarios"] == frozenset()
    assert graph["produtos"] == frozenset()
    assert graph["pedidos"] == frozenset({"usuarios", "produtos"})


def test_root_tables_sao_as_sem_dependencia() -> None:
    schema = load_schema(_schema_dict())
    graph = dependency_graph(schema)
    assert root_tables(graph) == frozenset({"usuarios", "produtos"})


def test_ready_tables_libera_filha_so_apos_pais_resolvidos() -> None:
    schema = load_schema(_schema_dict())
    graph = dependency_graph(schema)
    assert ready_tables(graph, frozenset()) == frozenset({"usuarios", "produtos"})
    assert ready_tables(graph, frozenset({"usuarios"})) == frozenset({"produtos"})
    assert ready_tables(graph, frozenset({"usuarios", "produtos"})) == frozenset({"pedidos"})


def test_has_cycle_detecta_ciclo_entre_tabelas() -> None:
    graph = {"a": frozenset({"b"}), "b": frozenset({"a"})}
    assert has_cycle(graph) is True


def test_has_cycle_falso_para_grafo_aciclico() -> None:
    schema = load_schema(_schema_dict())
    graph = dependency_graph(schema)
    assert has_cycle(graph) is False


def test_thread_participants_geram_arestas() -> None:
    data = _schema_dict()
    data["tables"].append(
        {
            "name": "conversas",
            "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
            "rows_from": {"via": "usuario_id", "relation": "thread"},
            "thread": {"participants": ["usuarios", "produtos"]},
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
            ],
        }
    )
    schema = load_schema(data)
    graph = dependency_graph(schema)
    assert graph["conversas"] == frozenset({"usuarios", "produtos"})
