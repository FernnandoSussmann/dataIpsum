"""Valida os exemplos de `examples/relacoes/` (DD-01 §B.7, B.8 critério B-10)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dataipsum.relations.planner import RelationsPlanner
from dataipsum.schema.loader import load_schema
from dataipsum.schema.models import ValidationContext, normalize_schema

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples" / "relacoes"
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.yaml"))


def test_existe_pelo_menos_um_exemplo() -> None:
    assert EXAMPLE_FILES


def test_readme_existe() -> None:
    assert (EXAMPLES_DIR / "README.md").exists()


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda path: path.name)
def test_exemplo_carrega_e_valida(path: Path) -> None:
    schema = load_schema(path)
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert errors == []


def test_um_para_muitos() -> None:
    schema = load_schema(EXAMPLES_DIR / "um-para-muitos.yaml")
    planner = RelationsPlanner()
    plan = planner.plan(schema, seed=schema.seed, chunk_size=schema.chunk_size)
    assert 200 <= plan.tables["pedidos_faixa"].rows <= 1000


def test_um_para_um() -> None:
    schema = load_schema(EXAMPLES_DIR / "um-para-um.yaml")
    planner = RelationsPlanner()
    plan = planner.plan(schema, seed=schema.seed, chunk_size=schema.chunk_size)
    assert plan.tables["perfis"].rows == 700


def test_muitos_para_muitos() -> None:
    schema = load_schema(EXAMPLES_DIR / "muitos-para-muitos.yaml")
    planner = RelationsPlanner()
    plan = planner.plan(schema, seed=schema.seed, chunk_size=schema.chunk_size)
    n = plan.tables["pedido_produto"].rows
    pares = planner.pk_at("pedido_produto", np.arange(n)).to_pylist()
    chaves = [(par["pedido_id"], par["produto_id"]) for par in pares]
    assert len(set(chaves)) == n


def test_cardinalidades() -> None:
    schema = load_schema(EXAMPLES_DIR / "cardinalidades.yaml")
    planner = RelationsPlanner()
    plan = planner.plan(schema, seed=schema.seed, chunk_size=schema.chunk_size)
    assert plan.tables["filhos_fixed"].rows == 300


def test_chaves() -> None:
    schema = load_schema(EXAMPLES_DIR / "chaves.yaml")
    planner = RelationsPlanner()
    planner.plan(schema, seed=schema.seed, chunk_size=schema.chunk_size)
    sequencial = planner.pk_at("sequencial", np.arange(5)).to_pylist()
    assert sequencial == [100, 110, 120, 130, 140]
    embaralhada = planner.pk_at("embaralhada", np.arange(500)).to_pylist()
    assert sorted(embaralhada) == list(range(1, 501))
    uuids = planner.pk_at("uuid", np.arange(500)).to_pylist()
    assert len(set(uuids)) == 500


def test_fk_distribuicao() -> None:
    schema = load_schema(EXAMPLES_DIR / "fk-distribuicao.yaml")
    planner = RelationsPlanner()
    planner.plan(schema, seed=schema.seed, chunk_size=schema.chunk_size)
    fks = planner.row_at("produtos", np.arange(5000), ["categoria_id"])["categoria_id"].to_pylist()
    assert min(fks) >= 1
    assert max(fks) <= 40


def test_thread_estrutura() -> None:
    schema = load_schema(EXAMPLES_DIR / "thread-estrutura.yaml")
    planner = RelationsPlanner()
    normalized = normalize_schema(schema, ValidationContext(planner=planner))
    plan = planner.plan(normalized, seed=schema.seed, chunk_size=schema.chunk_size)
    n = plan.tables["mensagens"].rows
    valores = planner.row_at("mensagens", np.arange(n), ["thread_id", "seq"])
    by_thread: dict[object, list[int]] = {}
    for thread_id, seq in zip(
        valores["thread_id"].to_pylist(), valores["seq"].to_pylist(), strict=True
    ):
        by_thread.setdefault(thread_id, []).append(seq)
    for seqs in by_thread.values():
        assert sorted(seqs) == list(range(1, len(seqs) + 1))
