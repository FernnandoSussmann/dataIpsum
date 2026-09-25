"""Testes de `RelationsPlanner` (DD-01 §B.3-B.6, §B.9)."""

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest

from dataipsum.contracts.generator import RowBatch
from dataipsum.errors import PlanError, ResourceLimitError
from dataipsum.relations.planner import RelationsPlanner
from dataipsum.schema.loader import load_schema
from dataipsum.schema.models import ValidationContext, normalize_schema


def _load(tables: list[dict], **schema_kwargs: object) -> object:
    document = {"version": 1, "name": "s", "chunk_size": 100, "tables": tables, **schema_kwargs}
    return load_schema(document)


def _root_table(name: str, rows: int, *, strategy: str = "sequence", start: int = 1) -> dict:
    return {
        "name": name,
        "rows": rows,
        "primary_key": {"columns": ["id"], "strategy": strategy, "start": start},
        "columns": [{"name": "id", "type": "int"}],
    }


def _one_to_many_table(
    name: str, parent: str, *, card_min: int, card_max: int, strategy: str = "seeded_int"
) -> dict:
    return {
        "name": name,
        "rows_from": {
            "via": "parent_id",
            "relation": "one_to_many",
            "cardinality": {"range": {"min": card_min, "max": card_max}},
        },
        "primary_key": {"columns": ["id"], "strategy": strategy, "start": 1},
        "columns": [
            {"name": "id", "type": "int"},
            {
                "name": "parent_id",
                "type": "ref",
                "params": {"table": parent},
                "null_ratio": 0.0,
            },
        ],
    }


class FakeIntGenerator:
    """Gerador fake determinístico (DD-01 §0: "B usa geradores fake para row_at")."""

    name = "fake_int"
    supports_invalid = False
    supports_format = False
    deterministic = True
    draw_slots = 1

    def validate_params(self, column, ctx):
        return []

    def logical_type(self, column):
        raise NotImplementedError

    def depends_on(self, column):
        return []

    def implied_columns(self, column):
        return []

    def generate(self, column, batch, draws, ctx):
        return pa.array(draws.integers(0, 0, 1000))


# --- plan() ---


def test_contagem_derivada_e_a_soma_da_cardinalidade() -> None:
    schema = _load(
        [
            _root_table("usuarios", 100),
            _one_to_many_table("pedidos", "usuarios", card_min=3, card_max=3),
        ]
    )
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=1, chunk_size=100)
    assert run_plan.tables["pedidos"].rows == 300


def test_cada_usuario_aparece_exatamente_a_cardinalidade_fixa() -> None:
    schema = _load(
        [
            _root_table("usuarios", 50),
            _one_to_many_table("pedidos", "usuarios", card_min=3, card_max=3),
        ]
    )
    planner = RelationsPlanner()
    planner.plan(schema, seed=1, chunk_size=1000)
    fks = planner.row_at("pedidos", np.arange(150), ["parent_id"])["parent_id"].to_pylist()
    parent_pks = planner.pk_at("usuarios", np.arange(50)).to_pylist()
    counts = {pk: fks.count(pk) for pk in parent_pks}
    assert all(count == 3 for count in counts.values())


def test_chunks_respeitam_chunk_size() -> None:
    schema = _load(
        [
            _root_table("usuarios", 1000),
            _one_to_many_table("pedidos", "usuarios", card_min=1, card_max=3),
        ]
    )
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=1, chunk_size=50)
    assert all(chunk.rows <= 50 for chunk in run_plan.tables["pedidos"].chunks)
    assert (
        sum(chunk.rows for chunk in run_plan.tables["pedidos"].chunks)
        == run_plan.tables["pedidos"].rows
    )


def test_pai_com_mais_filhos_que_chunk_size_e_partido() -> None:
    schema = _load(
        [
            _root_table("usuarios", 2),
            _one_to_many_table("pedidos", "usuarios", card_min=120, card_max=120),
        ]
    )
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=1, chunk_size=50)
    chunks = run_plan.tables["pedidos"].chunks
    assert all(chunk.rows <= 50 for chunk in chunks)
    assert len(chunks) == 6  # 2 pais * ceil(120/50) = 2*3


def test_plano_e_identico_para_a_mesma_entrada() -> None:
    schema = _load(
        [
            _root_table("usuarios", 200),
            _one_to_many_table("pedidos", "usuarios", card_min=1, card_max=5),
        ]
    )
    plan_a = RelationsPlanner().plan(schema, seed=7, chunk_size=64)
    plan_b = RelationsPlanner().plan(schema, seed=7, chunk_size=64)
    assert plan_a.to_json_dict() == plan_b.to_json_dict()


def test_resource_limit_error_antes_de_gerar_dados() -> None:
    schema = _load(
        [
            _root_table("usuarios", 1000),
            _one_to_many_table("pedidos", "usuarios", card_min=5, card_max=5),
        ],
        limits={"max_rows_total": 1000},
    )
    planner = RelationsPlanner()
    with pytest.raises(ResourceLimitError):
        planner.plan(schema, seed=1, chunk_size=100)


# --- 1:1 ---


def test_one_to_one_cobertura_produz_round_coverage_vezes_p() -> None:
    schema = _load(
        [
            _root_table("usuarios", 1000),
            {
                "name": "perfis",
                "rows_from": {"via": "usuario_id", "relation": "one_to_one", "coverage": 0.25},
                "primary_key": {"columns": ["id"], "strategy": "seeded_int", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                ],
            },
        ]
    )
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=1, chunk_size=1000)
    assert run_plan.tables["perfis"].rows == 250


def test_one_to_one_fk_e_unica() -> None:
    schema = _load(
        [
            _root_table("usuarios", 1000),
            {
                "name": "perfis",
                "rows_from": {"via": "usuario_id", "relation": "one_to_one", "coverage": 1.0},
                "primary_key": {"columns": ["id"], "strategy": "seeded_int", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                ],
            },
        ]
    )
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=1, chunk_size=1000)
    assert run_plan.tables["perfis"].rows == 1000
    fks = planner.row_at("perfis", np.arange(1000), ["usuario_id"])["usuario_id"].to_pylist()
    assert len(set(fks)) == 1000


# --- N:N ---


def _bridge_schema(pedidos_rows: int, produtos_rows: int, card_min: int, card_max: int) -> object:
    return _load(
        [
            _root_table("pedidos", pedidos_rows),
            _root_table("produtos", produtos_rows),
            {
                "name": "pedido_produto",
                "rows_from": {
                    "via": "pedido_id",
                    "relation": "many_to_many",
                    "pair": "produto_id",
                    "cardinality": {"range": {"min": card_min, "max": card_max}},
                },
                "primary_key": {"columns": ["pedido_id", "produto_id"], "strategy": "composite"},
                "columns": [
                    {"name": "pedido_id", "type": "ref", "params": {"table": "pedidos"}},
                    {"name": "produto_id", "type": "ref", "params": {"table": "produtos"}},
                ],
            },
        ]
    )


def test_n_para_n_nao_tem_pares_repetidos() -> None:
    schema = _bridge_schema(pedidos_rows=50, produtos_rows=50, card_min=1, card_max=5)
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=3, chunk_size=1000)
    n = run_plan.tables["pedido_produto"].rows
    pk = planner.pk_at("pedido_produto", np.arange(n)).to_pylist()
    pairs = [(row["pedido_id"], row["produto_id"]) for row in pk]
    assert len(set(pairs)) == len(pairs)


def test_n_para_n_max_card_maior_que_b_gera_plan_error() -> None:
    schema = _bridge_schema(pedidos_rows=5, produtos_rows=3, card_min=1, card_max=5)
    planner = RelationsPlanner()
    with pytest.raises(PlanError, match=r"max\(cardinalidade\)"):
        planner.plan(schema, seed=1, chunk_size=1000)


# --- FK não dirigente ---


def _non_dirigente_schema(
    population: int, *, distribution: dict | None = None, shuffle: bool | None = None
) -> object:
    params: dict[str, object] = {"table": "categorias"}
    if distribution is not None:
        params["distribution"] = distribution
    if shuffle is not None:
        params["shuffle"] = shuffle
    return _load(
        [
            _root_table("categorias", population),
            {
                "name": "produtos",
                "rows": 20_000,
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "categoria_id", "type": "ref", "params": params, "null_ratio": 0.1},
                ],
            },
        ]
    )


def test_fk_nao_dirigente_uniforme_qui_quadrado() -> None:
    schema = _non_dirigente_schema(10)
    planner = RelationsPlanner()
    planner.plan(schema, seed=1, chunk_size=20_000)
    fks = planner.row_at("produtos", np.arange(20_000), ["categoria_id"])[
        "categoria_id"
    ].to_pylist()
    counts = np.bincount([int(value) - 1 for value in fks], minlength=10)
    expected = 20_000 / 10
    chi_square = float(((counts - expected) ** 2 / expected).sum())
    # 9 graus de liberdade, limiar bem folgado (p ~ 0.001) para evitar flakiness.
    assert chi_square < 27.877


def test_fk_nao_dirigente_zipf_exata_p_pequeno() -> None:
    schema = _non_dirigente_schema(100, distribution={"zipf": {"s": 1.5}})
    planner = RelationsPlanner()
    planner.plan(schema, seed=2, chunk_size=20_000)
    fks = planner.row_at("produtos", np.arange(20_000), ["categoria_id"])[
        "categoria_id"
    ].to_pylist()
    assert min(fks) >= 1
    assert max(fks) <= 100
    assert len(set(fks)) > 1


def test_fk_nao_dirigente_zipf_aproximada_p_grande() -> None:
    schema = _non_dirigente_schema(1_100_000, distribution={"zipf": {"s": 1.2}})
    planner = RelationsPlanner()
    planner.plan(schema, seed=2, chunk_size=20_000)
    fks = planner.row_at("produtos", np.arange(2000), ["categoria_id"])["categoria_id"].to_pylist()
    assert min(fks) >= 1
    assert max(fks) <= 1_100_000


def test_fk_nao_dirigente_shuffle_muda_a_correlacao_com_a_ordem() -> None:
    shuffled_schema = _non_dirigente_schema(500, distribution={"zipf": {"s": 2.0}}, shuffle=True)
    unshuffled_schema = _non_dirigente_schema(500, distribution={"zipf": {"s": 2.0}}, shuffle=False)
    shuffled_planner = RelationsPlanner()
    shuffled_planner.plan(shuffled_schema, seed=9, chunk_size=20_000)
    unshuffled_planner = RelationsPlanner()
    unshuffled_planner.plan(unshuffled_schema, seed=9, chunk_size=20_000)
    shuffled = shuffled_planner.row_at("produtos", np.arange(5000), ["categoria_id"])[
        "categoria_id"
    ].to_pylist()
    unshuffled = unshuffled_planner.row_at("produtos", np.arange(5000), ["categoria_id"])[
        "categoria_id"
    ].to_pylist()
    assert shuffled != unshuffled


def test_fk_nao_dirigente_com_null_ratio_e_valida() -> None:
    schema = _non_dirigente_schema(10)
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert errors == []


# --- grafo ---


def test_validate_reporta_ciclo() -> None:
    schema = _load(
        [
            {
                "name": "a",
                "rows": 5,
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "b_id", "type": "ref", "params": {"table": "b"}},
                ],
            },
            {
                "name": "b",
                "rows": 5,
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "a_id", "type": "ref", "params": {"table": "a"}},
                ],
            },
        ]
    )
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert any("a → b → a" in error.message for error in errors)


# --- threads ---


def _thread_schema(*, card_min: int = 4, card_max: int = 12, participant_count: int = 2) -> object:
    planner = RelationsPlanner()
    raw = {
        "version": 1,
        "name": "th",
        "seed": 7,
        "chunk_size": 1000,
        "tables": [
            _root_table("pessoas", 20),
            _root_table("conversas", 5),
            {
                "name": "mensagens",
                "rows_from": {
                    "via": "thread_id",
                    "relation": "thread",
                    "cardinality": {"range": {"min": card_min, "max": card_max}},
                },
                "thread": {
                    "participants": {
                        "table": "pessoas",
                        "count": participant_count,
                        "label_column": "id",
                    },
                    "start": {"min": "2024-01-01T00:00:00", "max": "2024-01-02T00:00:00"},
                    "gap_seconds": {"min": 1, "max": 60},
                },
                "primary_key": {"columns": ["id"], "strategy": "seeded_int", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "thread_id", "type": "ref", "params": {"table": "conversas"}},
                ],
            },
        ],
    }
    schema = load_schema(raw)
    return normalize_schema(schema, ValidationContext(planner=planner))


def test_thread_nomes_reservados_sao_rejeitados() -> None:
    schema = _load(
        [
            _root_table("pessoas", 5),
            _root_table("conversas", 3),
            {
                "name": "mensagens",
                "rows_from": {
                    "via": "thread_id",
                    "relation": "thread",
                    "cardinality": {"range": {"min": 2, "max": 4}},
                },
                "thread": {
                    "participants": {"table": "pessoas", "count": 2, "label_column": "id"},
                    "start": {"min": "2024-01-01T00:00:00", "max": "2024-01-02T00:00:00"},
                    "gap_seconds": {"min": 1, "max": 10},
                },
                "primary_key": {"columns": ["id"], "strategy": "seeded_int", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "thread_id", "type": "ref", "params": {"table": "conversas"}},
                    {"name": "seq", "type": "int"},
                ],
            },
        ]
    )
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert any("seq" in error.message for error in errors)


def test_thread_implied_columns_na_ordem_esperada() -> None:
    planner = RelationsPlanner()
    table = load_schema(
        {
            "version": 1,
            "name": "th",
            "chunk_size": 100,
            "tables": [
                _root_table("pessoas", 5),
                _root_table("conversas", 3),
                {
                    "name": "mensagens",
                    "rows_from": {
                        "via": "thread_id",
                        "relation": "thread",
                        "cardinality": {"range": {"min": 2, "max": 4}},
                    },
                    "thread": {
                        "participants": {"table": "pessoas", "count": 2, "label_column": "id"},
                        "start": {"min": "2024-01-01T00:00:00", "max": "2024-01-02T00:00:00"},
                        "gap_seconds": {"min": 1, "max": 10},
                    },
                    "primary_key": {"columns": ["id"], "strategy": "seeded_int", "start": 1},
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "thread_id", "type": "ref", "params": {"table": "conversas"}},
                    ],
                },
            ],
        }
    ).tables[2]
    implied = planner.implied_columns(table)
    assert [column.name for column in implied] == [
        "seq",
        "autor",
        "timestamp",
        "texto",
        "is_offensive",
        "is_placeholder",
    ]


def test_thread_participantes_distintos() -> None:
    schema = _thread_schema(participant_count=3)
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=7, chunk_size=1000)
    n = run_plan.tables["mensagens"].rows
    values = planner.row_at("mensagens", np.arange(n), ["thread_id", "autor"])
    threads = values["thread_id"].to_pylist()
    autores = values["autor"].to_pylist()
    by_thread: dict[object, set[object]] = {}
    for thread_id, autor in zip(threads, autores, strict=True):
        by_thread.setdefault(thread_id, set()).add(autor)
    assert all(len(distinct) <= 3 for distinct in by_thread.values())


def test_thread_autor_diferente_do_anterior() -> None:
    schema = _thread_schema()
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=7, chunk_size=1000)
    n = run_plan.tables["mensagens"].rows
    values = planner.row_at("mensagens", np.arange(n), ["thread_id", "seq", "autor"])
    rows = sorted(
        zip(
            values["thread_id"].to_pylist(),
            values["seq"].to_pylist(),
            values["autor"].to_pylist(),
            strict=True,
        )
    )
    previous_by_thread: dict[object, object] = {}
    for thread_id, _seq, autor in rows:
        assert previous_by_thread.get(thread_id) != autor
        previous_by_thread[thread_id] = autor


def test_thread_timestamps_estritamente_crescentes_por_seq() -> None:
    schema = _thread_schema()
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=7, chunk_size=1000)
    n = run_plan.tables["mensagens"].rows
    values = planner.row_at("mensagens", np.arange(n), ["thread_id", "seq", "timestamp"])
    rows = sorted(
        zip(
            values["thread_id"].to_pylist(),
            values["seq"].to_pylist(),
            values["timestamp"].to_pylist(),
            strict=True,
        )
    )
    previous_by_thread: dict[object, object] = {}
    for thread_id, _seq, timestamp in rows:
        previous = previous_by_thread.get(thread_id)
        if previous is not None:
            assert timestamp > previous
        previous_by_thread[thread_id] = timestamp


def test_thread_seq_vai_de_1_a_n() -> None:
    schema = _thread_schema()
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=7, chunk_size=1000)
    n = run_plan.tables["mensagens"].rows
    values = planner.row_at("mensagens", np.arange(n), ["thread_id", "seq"])
    by_thread: dict[object, list[int]] = {}
    for thread_id, seq in zip(
        values["thread_id"].to_pylist(), values["seq"].to_pylist(), strict=True
    ):
        by_thread.setdefault(thread_id, []).append(seq)
    for seqs in by_thread.values():
        assert sorted(seqs) == list(range(1, len(seqs) + 1))


def test_thread_nao_e_partida_entre_chunks() -> None:
    schema = _thread_schema(card_min=200, card_max=200, participant_count=2)
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=7, chunk_size=50)
    chunks = run_plan.tables["mensagens"].chunks
    # cardinalidade fixa 200 > chunk_size 50: cada thread inteira vira 1 chunk (>50 linhas).
    assert all(chunk.rows == 200 for chunk in chunks)


# --- row_at / pk_at ---


def test_row_at_e_igual_a_linha_da_geracao_completa() -> None:
    schema = _load(
        [
            _root_table("usuarios", 500),
            _one_to_many_table("pedidos", "usuarios", card_min=1, card_max=4),
        ]
    )
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=99, chunk_size=64)
    n = run_plan.tables["pedidos"].rows
    full = planner.row_at("pedidos", np.arange(n), ["id", "parent_id"])
    single = planner.row_at("pedidos", np.array([n - 1]), ["id", "parent_id"])
    assert full["id"].to_pylist()[-1] == single["id"].to_pylist()[0]
    assert full["parent_id"].to_pylist()[-1] == single["parent_id"].to_pylist()[0]


def test_row_at_recalcula_a_linha_do_pai() -> None:
    schema = _load([_root_table("usuarios", 10_000, strategy="seeded_int")])
    planner = RelationsPlanner()
    planner.plan(schema, seed=99, chunk_size=1000)
    full = planner.row_at("usuarios", np.arange(10_000), ["id"])["id"].to_pylist()
    single = planner.row_at("usuarios", np.array([4321]), ["id"])["id"].to_pylist()
    assert full[4321] == single[0]


def test_row_at_com_coluna_llm_gera_plan_error() -> None:
    schema = _thread_schema()
    planner = RelationsPlanner()
    planner.plan(schema, seed=7, chunk_size=1000)
    with pytest.raises(PlanError, match="não determinística"):
        planner.row_at("mensagens", np.array([0]), ["texto"])


def test_row_at_delega_para_gerador_fake_de_coluna_comum() -> None:
    schema = _load([_root_table("usuarios", 100)])
    planner = RelationsPlanner(generators={"fake_int": FakeIntGenerator()})
    planner.plan(schema, seed=1, chunk_size=100)
    values = planner.row_at("usuarios", np.array([0, 1]), ["id"])
    assert values["id"].to_pylist() == [1, 2]


def test_cache_lru_nao_altera_o_resultado() -> None:
    schema = _load(
        [
            _root_table("usuarios", 2000),
            _one_to_many_table("pedidos", "usuarios", card_min=1, card_max=3),
        ]
    )
    planner = RelationsPlanner()
    planner.plan(schema, seed=5, chunk_size=200)
    n = planner._run_plan.tables["pedidos"].rows  # noqa: SLF001 - acesso de teste ao estado interno
    baseline = planner.row_at("pedidos", np.arange(n), ["parent_id"])["parent_id"].to_pylist()
    for _ in range(200):
        planner.row_at("pedidos", np.array([0]), ["parent_id"])
    repeated = planner.row_at("pedidos", np.arange(n), ["parent_id"])["parent_id"].to_pylist()
    assert baseline == repeated


def test_chunk_size_diferente_nao_altera_valores_gerados() -> None:
    schema = _load(
        [
            _root_table("usuarios", 500),
            _one_to_many_table("pedidos", "usuarios", card_min=1, card_max=4),
        ]
    )
    planner_a = RelationsPlanner()
    plan_a = planner_a.plan(schema, seed=5, chunk_size=500)
    planner_b = RelationsPlanner()
    plan_b = planner_b.plan(schema, seed=5, chunk_size=17)
    assert plan_a.tables["pedidos"].rows == plan_b.tables["pedidos"].rows
    n = plan_a.tables["pedidos"].rows
    values_a = planner_a.row_at("pedidos", np.arange(n), ["id", "parent_id"])
    values_b = planner_b.row_at("pedidos", np.arange(n), ["id", "parent_id"])
    assert values_a["id"].to_pylist() == values_b["id"].to_pylist()
    assert values_a["parent_id"].to_pylist() == values_b["parent_id"].to_pylist()


# --- parent_index_of ---


def test_parent_index_of_bate_com_o_intervalo_de_pks_do_pai() -> None:
    schema = _load(
        [
            _root_table("usuarios", 300),
            _one_to_many_table("pedidos", "usuarios", card_min=2, card_max=2),
        ]
    )
    planner = RelationsPlanner()
    run_plan = planner.plan(schema, seed=1, chunk_size=1000)
    chunk = run_plan.tables["pedidos"].chunks[0]
    rows = np.arange(chunk.first_row, chunk.first_row + chunk.rows)
    parent_idx = planner.parent_index_of("pedidos", chunk, RowBatch(rows=rows))
    parent_pks = set(planner.pk_at("usuarios", np.arange(300)).to_pylist())
    resolved_pks = set(planner.pk_at("usuarios", parent_idx).to_pylist())
    assert resolved_pks <= parent_pks


# --- validação ---


def test_validate_rejeita_via_nao_ref() -> None:
    schema = _load(
        [
            _root_table("usuarios", 10),
            {
                "name": "pedidos",
                "rows_from": {
                    "via": "usuario_id",
                    "relation": "one_to_many",
                    "cardinality": {"range": {"min": 1, "max": 2}},
                },
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "usuario_id", "type": "int"},
                ],
            },
        ]
    )
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert any("via" in error.message for error in errors)


def test_validate_rejeita_ref_para_tabela_inexistente() -> None:
    schema = _load(
        [
            {
                "name": "pedidos",
                "rows": 10,
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                ],
            }
        ]
    )
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert any("inexistente" in error.message for error in errors)


def test_validate_rejeita_coverage_em_one_to_many() -> None:
    schema = _load(
        [
            _root_table("usuarios", 10),
            {
                "name": "pedidos",
                "rows_from": {"via": "usuario_id", "relation": "one_to_many", "coverage": 0.5},
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                ],
            },
        ]
    )
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert any("coverage" in error.message for error in errors)


def test_validate_rejeita_cardinalidade_em_one_to_one() -> None:
    schema = _load(
        [
            _root_table("usuarios", 10),
            {
                "name": "perfis",
                "rows_from": {
                    "via": "usuario_id",
                    "relation": "one_to_one",
                    "cardinality": {"range": {"min": 1, "max": 2}},
                },
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                ],
            },
        ]
    )
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert any("cardinality" in error.message for error in errors)


def test_validate_rejeita_cardinalidade_acima_do_maximo() -> None:
    schema = _load(
        [
            _root_table("usuarios", 10),
            _one_to_many_table("pedidos", "usuarios", card_min=1, card_max=2_000_000),
        ]
    )
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert any("máximo" in error.message for error in errors)


def test_validate_rejeita_many_to_many_sem_pair() -> None:
    schema = _load(
        [
            _root_table("pedidos", 10),
            _root_table("produtos", 10),
            {
                "name": "pedido_produto",
                "rows_from": {
                    "via": "pedido_id",
                    "relation": "many_to_many",
                    "cardinality": {"range": {"min": 1, "max": 2}},
                },
                "primary_key": {"columns": ["pedido_id"], "strategy": "sequence", "start": 1},
                "columns": [{"name": "pedido_id", "type": "ref", "params": {"table": "pedidos"}}],
            },
        ]
    )
    planner = RelationsPlanner()
    errors = planner.validate(schema)
    assert any("pair" in error.message for error in errors)


def test_sequence_overflow_e_rejeitado() -> None:
    schema = _load([_root_table("usuarios", 10, strategy="sequence")])
    schema.tables[0].primary_key.start = 2**63 - 5
    planner = RelationsPlanner()
    with pytest.raises(PlanError, match="estoura"):
        planner.plan(schema, seed=1, chunk_size=100)
