"""Testes de `graph.topological_order` (DD-01 §B.3.4, §B.6, §B.9)."""

from __future__ import annotations

import pytest

from dataipsum.errors import PlanError
from dataipsum.relations import graph
from dataipsum.schema.loader import load_schema


def _table(name: str, *, ref_to: str | None = None, ref_column: str = "parent_id") -> dict:
    columns = [{"name": "id", "type": "int"}]
    if ref_to is not None:
        columns.append(
            {"name": ref_column, "type": "ref", "params": {"table": ref_to}, "null_ratio": 0.0}
        )
    return {
        "name": name,
        "rows": 10,
        "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
        "columns": columns,
    }


def _schema(tables: list[dict]) -> object:
    return load_schema({"version": 1, "name": "g", "chunk_size": 100, "tables": tables})


def test_ordem_topologica_coloca_alvo_antes_de_quem_referencia() -> None:
    schema = _schema([_table("pedidos", ref_to="usuarios"), _table("usuarios")])
    order = graph.topological_order(schema)
    assert order.index("usuarios") < order.index("pedidos")


def test_tabelas_independentes_aparecem_todas() -> None:
    schema = _schema([_table("a"), _table("b"), _table("c")])
    assert set(graph.topological_order(schema)) == {"a", "b", "c"}


def test_ciclo_entre_duas_tabelas_gera_plan_error_com_caminho() -> None:
    schema = _schema(
        [
            _table("a", ref_to="b", ref_column="b_id"),
            _table("b", ref_to="a", ref_column="a_id"),
        ]
    )
    with pytest.raises(PlanError, match=r"a → b → a"):
        graph.topological_order(schema)


def test_auto_referencia_gera_plan_error() -> None:
    schema = _schema([_table("a", ref_to="a", ref_column="parent_id")])
    with pytest.raises(PlanError, match="auto-referência"):
        graph.topological_order(schema)
