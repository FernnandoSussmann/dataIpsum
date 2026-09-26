"""Testes do construtor de chunk (DD-01 §D.3.2, §D.6): ordem de colunas, nulos
aplicados depois do gerador, PK nunca nula, determinismo."""

from __future__ import annotations

from dataclasses import dataclass

import pyarrow as pa
import pytest

from dataipsum.contracts.executor import ChunkTask
from dataipsum.contracts.generator import RowBatch
from dataipsum.contracts.planner import ChunkSpec
from dataipsum.errors import SchemaError
from dataipsum.execution.chunk_builder import build_chunk, build_record_batch
from dataipsum.registry import Registry
from dataipsum.schema.loader import load_schema
from dataipsum.testing.fakes import FakePlanner, FakeSink


@dataclass
class _ConstGenerator:
    """Gerador fake: devolve o índice da linha; marca inválido/nulo na ordem de
    chamada (assinado numa lista de módulo para os testes checarem a ordem)."""

    name: str = "const"
    supports_invalid: bool = True
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 2

    def validate_params(self, column: object, ctx: object) -> list[object]:
        return []

    def logical_type(self, column: object) -> object:
        return None

    def depends_on(self, column: object) -> list[str]:
        return []

    def implied_columns(self, column: object) -> list[object]:
        return []

    def generate(self, column: object, batch: RowBatch, draws: object, ctx: object) -> pa.Array:
        return pa.array(batch.rows.tolist(), type=pa.int64())


@dataclass
class _DependentGenerator(_ConstGenerator):
    """Depende da coluna `id` já gerada no mesmo chunk (`ctx.same_row`)."""

    name: str = "dependent"

    def depends_on(self, column: object) -> list[str]:
        return ["id"]

    def generate(self, column: object, batch: RowBatch, draws: object, ctx: object) -> pa.Array:
        same = ctx.same_row(["id"])
        return pa.array([f"e{value}" for value in same["id"].to_pylist()])


@dataclass
class _LocaleSpyGenerator(_ConstGenerator):
    """Devolve `ctx.locale` como valor, para testar a precedência coluna >
    tabela > schema (DD-00 `effective_locale`, DD-01 §A.3/A.6)."""

    name: str = "locale_spy"

    def generate(self, column: object, batch: RowBatch, draws: object, ctx: object) -> pa.Array:
        return pa.array([ctx.locale] * len(batch.rows))


def _registry() -> Registry:
    registry = Registry()
    registry.register_generator("const", _ConstGenerator)
    registry.register_generator("dependent", _DependentGenerator)
    registry.register_generator("locale_spy", _LocaleSpyGenerator)
    return registry


def _schema_dict(*, null_ratio: float = 0.0) -> dict[str, object]:
    return {
        "version": 1,
        "name": "loja",
        "tables": [
            {
                "name": "usuarios",
                "rows": 6,
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 0},
                "columns": [
                    {"name": "id", "type": "const"},
                    {"name": "apelido", "type": "dependent", "null_ratio": null_ratio},
                ],
            }
        ],
    }


def _task(schema: object, *, first_row: int = 0, rows: int = 6) -> ChunkTask:
    return ChunkTask(
        table="usuarios",
        chunk_spec=ChunkSpec(id=0, first_row=first_row, rows=rows),
        schema=schema,
        root_seed=42,
        sink_options={},
        run_options={},
    )


def test_ordem_de_colunas_segue_a_declaracao_do_schema() -> None:
    schema = load_schema(_schema_dict())
    batch, _flags, llm_pending, _should_write = build_record_batch(
        _task(schema), planner=FakePlanner(), registry=_registry()
    )
    assert batch.schema.names == ["id", "apelido"]
    assert llm_pending is False


def test_locale_efetivo_segue_precedencia_coluna_tabela_schema() -> None:
    """DD-00 `effective_locale`, DD-01 §A.3/A.6: coluna > tabela > schema. Cada
    coluna resolve o locale de forma independente — uma tabela com duas colunas
    `locale_spy`, uma sem override e outra com `locale: "fr_FR"`, deve produzir
    valores diferentes para cada uma."""
    schema = load_schema(
        {
            "version": 1,
            "name": "loja",
            "locale": "pt_BR",
            "tables": [
                {
                    "name": "usuarios",
                    "rows": 3,
                    "locale": "en_US",
                    "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 0},
                    "columns": [
                        {"name": "id", "type": "const"},
                        {"name": "herdado_da_tabela", "type": "locale_spy"},
                        {"name": "override_na_coluna", "type": "locale_spy", "locale": "fr_FR"},
                    ],
                }
            ],
        }
    )
    batch, _flags, _pending, _sw = build_record_batch(
        _task(schema, rows=3), planner=FakePlanner(), registry=_registry()
    )
    assert batch.column("herdado_da_tabela").to_pylist() == ["en_US"] * 3
    assert batch.column("override_na_coluna").to_pylist() == ["fr_FR"] * 3


def test_pk_vem_do_planner_e_nunca_e_nula() -> None:
    schema = load_schema(_schema_dict(null_ratio=1.0))
    batch, _flags, _pending, _should_write = build_record_batch(
        _task(schema), planner=FakePlanner(), registry=_registry()
    )
    assert batch.column("id").to_pylist() == [0, 1, 2, 3, 4, 5]
    assert batch.column("id").null_count == 0


def test_dependente_ve_a_coluna_ja_gerada_no_mesmo_chunk() -> None:
    schema = load_schema(_schema_dict())
    batch, _flags, _pending, _should_write = build_record_batch(
        _task(schema), planner=FakePlanner(), registry=_registry()
    )
    assert batch.column("apelido").to_pylist() == ["e0", "e1", "e2", "e3", "e4", "e5"]


def test_nulos_sao_aplicados_depois_do_gerador() -> None:
    schema = load_schema(_schema_dict(null_ratio=1.0))
    batch, _flags, _pending, _should_write = build_record_batch(
        _task(schema), planner=FakePlanner(), registry=_registry()
    )
    # null_ratio=1.0 força todas as células a nulo, mesmo que o gerador tenha produzido valor.
    assert batch.column("apelido").null_count == 6


def test_chunk_reconstruido_e_deterministico() -> None:
    schema = load_schema(_schema_dict())
    batch1, _flags1, _pending1, _sw1 = build_record_batch(
        _task(schema), planner=FakePlanner(), registry=_registry()
    )
    batch2, _flags2, _pending2, _sw2 = build_record_batch(
        _task(schema), planner=FakePlanner(), registry=_registry()
    )
    assert batch1.equals(batch2)


def test_ciclo_de_dependencias_entre_colunas_e_schema_error() -> None:
    @dataclass
    class _CycleA(_ConstGenerator):
        name: str = "cycle_a"

        def depends_on(self, column: object) -> list[str]:
            return ["b"]

    @dataclass
    class _CycleB(_ConstGenerator):
        name: str = "cycle_b"

        def depends_on(self, column: object) -> list[str]:
            return ["a"]

    registry = Registry()
    registry.register_generator("cycle_a", _CycleA)
    registry.register_generator("cycle_b", _CycleB)
    data = {
        "version": 1,
        "tables": [
            {
                "name": "t",
                "rows": 1,
                "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 0},
                "columns": [
                    {"name": "id", "type": "cycle_a"},
                    {"name": "a", "type": "cycle_a"},
                    {"name": "b", "type": "cycle_b"},
                ],
            }
        ],
    }
    schema = load_schema(data)
    task = ChunkTask(
        table="t",
        chunk_spec=ChunkSpec(id=0, first_row=0, rows=1),
        schema=schema,
        root_seed=1,
        sink_options={},
        run_options={},
    )
    with pytest.raises(SchemaError):
        build_record_batch(task, planner=FakePlanner(), registry=registry)


def test_build_chunk_escreve_no_sink_e_devolve_sha256() -> None:
    schema = load_schema(_schema_dict())
    sink = FakeSink()
    result = build_chunk(_task(schema), planner=FakePlanner(), registry=_registry(), sink=sink)
    assert result.status == "done"
    assert result.rows == 6
    assert result.sink_ref == "fake://0"
    assert 0 in sink.batches


@dataclass
class _CompositePkPlanner(FakePlanner):
    """PK composta (`many_to_many`, DD-01 §B.3.5): `pk_at` devolve um `StructArray` com um
    campo por coluna da chave — regressão de um bug em que `build_record_batch` atribuía o
    mesmo `StructArray` inteiro a cada nome da chave, em vez de decompor os campos."""

    def pk_at(self, table: str, indices: object) -> pa.Array:  # type: ignore[override]
        rows = pa.array(indices).to_pylist()
        return pa.StructArray.from_arrays(
            [pa.array(rows, type=pa.int64()), pa.array([r * 10 for r in rows], type=pa.int64())],
            names=["a_id", "b_id"],
        )


def test_pk_composta_e_decomposta_em_colunas_proprias() -> None:
    data = {
        "version": 1,
        "tables": [
            {
                "name": "ponte",
                "rows_from": {
                    "via": "a_id",
                    "relation": "many_to_many",
                    "pair": "b_id",
                    "cardinality": {"range": {"min": 1, "max": 1}},
                },
                "primary_key": {"columns": ["a_id", "b_id"], "strategy": "composite"},
                "columns": [
                    {"name": "a_id", "type": "ref", "params": {"table": "ponte"}},
                    {"name": "b_id", "type": "ref", "params": {"table": "ponte"}},
                ],
            }
        ],
    }
    schema = load_schema(data)
    task = ChunkTask(
        table="ponte",
        chunk_spec=ChunkSpec(id=0, first_row=0, rows=4),
        schema=schema,
        root_seed=1,
        sink_options={},
        run_options={},
    )
    batch, _flags, _pending, _sw = build_record_batch(
        task, planner=_CompositePkPlanner(), registry=_registry()
    )
    assert batch.column("a_id").to_pylist() == [0, 1, 2, 3]
    assert batch.column("b_id").to_pylist() == [0, 10, 20, 30]
