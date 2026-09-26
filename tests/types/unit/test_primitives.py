"""Testes dos geradores primitivos (DD-01 A.6): string, char, int, float, decimal,
boolean, date, time, timestamp, uuid, json, array."""

from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal

import numpy as np
import pytest


def test_registry_tem_os_17_tipos(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    esperados = {
        "string",
        "char",
        "int",
        "float",
        "decimal",
        "boolean",
        "date",
        "time",
        "timestamp",
        "uuid",
        "json",
        "array",
        "cpf",
        "rg",
        "cartao_credito",
        "nome_proprio",
        "email",
    }
    assert esperados <= set(registry.generators)
    assert "pt_BR" in registry.locales


def test_indices_nao_contiguos_igual_a_lote_contiguo(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("int", params={"min": 0, "max": 1000})
    generator = registry.get_generator("int")()
    ctx = gen_context_factory()

    rows_contig = np.arange(10, 20, dtype=np.int64)
    from dataipsum.contracts.generator import RowBatch
    from dataipsum.seeds import Draws, seed_column, seed_table

    seed_col = seed_column(seed_table(1, "t"), "c")
    contig = generator.generate(
        column, RowBatch(rows=rows_contig), Draws(seed_col=seed_col, rows=rows_contig), ctx
    )

    rows_sparse = np.array([10, 12, 15, 19], dtype=np.int64)
    sparse = generator.generate(
        column, RowBatch(rows=rows_sparse), Draws(seed_col=seed_col, rows=rows_sparse), ctx
    )

    expected_indices = [rows_contig.tolist().index(r) for r in rows_sparse]
    assert sparse.to_pylist() == [contig.to_pylist()[i] for i in expected_indices]


def test_determinismo_mesma_seed_mesmo_resultado(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("string", max_length=20)
    first = generate_column(registry, column, seed=7)
    second = generate_column(registry, column, seed=7)
    assert first.to_pylist() == second.to_pylist()


def test_seed_diferente_muda_resultado(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("string", max_length=20)
    first = generate_column(registry, column, seed=7)
    second = generate_column(registry, column, seed=8)
    assert first.to_pylist() != second.to_pylist()


# --- string ---------------------------------------------------------------


def test_string_respeita_min_e_max_length(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("string", params={"min_length": 2, "charset": "alnum"}, max_length=8)
    values = generate_column(registry, column, row_count=2000).to_pylist()
    assert all(2 <= len(v) <= 8 for v in values)


def test_string_charset_alpha_so_usa_letras(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("string", params={"charset": "alpha"}, max_length=30)
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(re.fullmatch(r"[A-Za-z]*", v) for v in values)


def test_string_charset_alnum_so_usa_letras_e_digitos(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("string", params={"charset": "alnum"}, max_length=30)
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(re.fullmatch(r"[A-Za-z0-9]*", v) for v in values)


def test_string_lorem_nunca_ultrapassa_max_length(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("string", params={"charset": "lorem"}, max_length=15)
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(len(v) <= 15 for v in values)


def test_string_comprimentos_0_e_n_ocorrem(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("string", params={"min_length": 0}, max_length=10)
    values = generate_column(registry, column, row_count=100_000).to_pylist()
    lengths = {len(v) for v in values}
    assert 0 in lengths
    assert 10 in lengths


def test_string_logical_type(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("string")()
    column = column_factory("string", max_length=42)
    assert generator.logical_type(column).kind == "string"
    assert generator.logical_type(column).max_length == 42


def test_string_max_length_obrigatorio(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("string")()
    column = column_factory("string", max_length=None)
    errors = generator.validate_params(column, None)
    assert any(error.path == "max_length" for error in errors)


def test_string_max_length_acima_do_teto_e_erro(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("string")()
    column = column_factory("string", max_length=2_000_000)
    errors = generator.validate_params(column, None)
    assert any(error.path == "max_length" for error in errors)


def test_string_parametro_desconhecido_e_erro(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("string")()
    column = column_factory("string", params={"bogus": 1}, max_length=10)
    errors = generator.validate_params(column, None)
    assert any(error.path == "bogus" for error in errors)


# --- char -------------------------------------------------------------


def test_char_comprimento_fixo(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("char", params={"length": 7})
    values = generate_column(registry, column, row_count=200).to_pylist()
    assert all(len(v) == 7 for v in values)


def test_char_logical_type(registry, column_factory, generate_column, gen_context_factory) -> None:
    generator = registry.get_generator("char")()
    column = column_factory("char", params={"length": 5})
    assert generator.logical_type(column).kind == "char"
    assert generator.logical_type(column).length == 5


# --- int ---------------------------------------------------------------


def test_int_respeita_min_e_max(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("int", params={"min": 5, "max": 9})
    values = generate_column(registry, column, row_count=1000).to_pylist()
    assert all(5 <= v <= 9 for v in values)


def test_int_logical_type_int32_quando_cabe(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("int")()
    column = column_factory("int", params={"min": 0, "max": 100})
    assert generator.logical_type(column).kind == "int32"


def test_int_logical_type_int64_quando_nao_cabe(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("int")()
    column = column_factory("int", params={"min": 0, "max": 2**40})
    assert generator.logical_type(column).kind == "int64"


def test_int_min_maior_que_max_e_erro(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("int")()
    column = column_factory("int", params={"min": 10, "max": 1})
    errors = generator.validate_params(column, None)
    assert any(error.path == "min" for error in errors)


# --- float --------------------------------------------------------------


def test_float_respeita_min_e_max(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("float", params={"min": -1.0, "max": 1.0})
    values = generate_column(registry, column, row_count=1000).to_pylist()
    assert all(-1.0 <= v <= 1.0 for v in values)


def test_float_arredonda_com_decimals(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("float", params={"min": 0.0, "max": 1.0, "decimals": 2})
    values = generate_column(registry, column, row_count=1000).to_pylist()
    assert all(round(v, 2) == v for v in values)


# --- decimal -------------------------------------------------------------


def test_decimal_valores_exatos_e_cabem_em_precision(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory(
        "decimal", params={"precision": 6, "scale": 2, "min": "0.00", "max": "999.99"}
    )
    values = generate_column(registry, column, row_count=1000).to_pylist()
    assert all(isinstance(v, Decimal) for v in values)
    assert all(Decimal("0.00") <= v <= Decimal("999.99") for v in values)
    assert all(-v.as_tuple().exponent == 2 for v in values)


def test_decimal_logical_type(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("decimal")()
    column = column_factory("decimal", params={"precision": 8, "scale": 3})
    logical = generator.logical_type(column)
    assert (logical.precision, logical.scale) == (8, 3)


def test_decimal_scale_maior_que_precision_e_erro(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("decimal")()
    column = column_factory("decimal", params={"precision": 3, "scale": 5})
    errors = generator.validate_params(column, None)
    assert any(error.path == "scale" for error in errors)


# --- boolean ---------------------------------------------------------------


def test_boolean_true_ratio_aproximado(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("boolean", params={"true_ratio": 0.2})
    values = generate_column(registry, column, row_count=100_000).to_pylist()
    ratio = sum(values) / len(values)
    assert 0.19 <= ratio <= 0.21


# --- date / time / timestamp -----------------------------------------------


def test_date_limites_inclusivos(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("date", params={"min": "2020-01-01", "max": "2020-01-03"})
    values = generate_column(registry, column, row_count=2000).to_pylist()
    assert set(values) <= {dt.date(2020, 1, 1), dt.date(2020, 1, 2), dt.date(2020, 1, 3)}
    assert dt.date(2020, 1, 1) in values
    assert dt.date(2020, 1, 3) in values


def test_time_precisao_ms(registry, column_factory, generate_column, gen_context_factory) -> None:
    generator = registry.get_generator("time")()
    column = column_factory("time", params={"precision": "ms"})
    assert generator.generate.__name__ == "generate"
    values = generate_column(registry, column, row_count=10)
    assert values.type == __import__("pyarrow").time32("ms")


def test_timestamp_timezone_reflete_no_tipo_arrow(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column_tz = column_factory("timestamp", params={"timezone": True})
    column_no_tz = column_factory("timestamp", params={"timezone": False})
    with_tz = generate_column(registry, column_tz, row_count=10)
    without_tz = generate_column(registry, column_no_tz, row_count=10)
    assert with_tz.type.tz == "UTC"
    assert without_tz.type.tz is None


# --- uuid --------------------------------------------------------------


@pytest.mark.slow
def test_uuid_versao_4_e_variante_rfc4122(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("uuid")
    values = generate_column(registry, column, row_count=100_000).to_pylist()
    pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    assert all(pattern.fullmatch(value) for value in values)


def test_uuid_formato_basico(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory("uuid")
    values = generate_column(registry, column, row_count=200).to_pylist()
    assert len(set(values)) == len(values)


# --- json / array -----------------------------------------------------------


def test_json_e_parseavel_com_campos_na_ordem_declarada(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory(
        "json",
        params={
            "fields": {
                "a": {"type": "int", "params": {"min": 0, "max": 9}},
                "b": {"type": "boolean"},
            }
        },
    )
    values = generate_column(registry, column, row_count=50).to_pylist()
    for value in values:
        parsed = json.loads(value)
        assert list(parsed.keys()) == ["a", "b"]


def test_json_profundidade_maior_que_3_e_rejeitada(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    generator = registry.get_generator("json")()
    column = column_factory("json", params={"fields": {"a": {"type": "int"}}, "max_depth": 4})
    errors = generator.validate_params(column, None)
    assert any(error.path == "max_depth" for error in errors)


def test_array_max_items_respeitado(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory(
        "array", params={"items": {"type": "int", "params": {"min": 0, "max": 9}}, "max_items": 3}
    )
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(len(v) <= 3 for v in values)


def test_array_min_items_respeitado(
    registry, column_factory, generate_column, gen_context_factory
) -> None:
    column = column_factory(
        "array",
        params={
            "items": {"type": "int", "params": {"min": 0, "max": 9}},
            "min_items": 2,
            "max_items": 2,
        },
    )
    values = generate_column(registry, column, row_count=200).to_pylist()
    assert all(len(v) == 2 for v in values)


def test_invalid_ratio_em_primitivo_e_erro_de_capacidade() -> None:
    from dataipsum.registry import Registry
    from dataipsum.schema.models import Schema, ValidationContext, validate_with_registry
    from dataipsum.types import register as register_types

    registry_instance = Registry()
    register_types(registry_instance)
    generators = {
        name: registry_instance.get_generator(name)() for name in registry_instance.generators
    }
    schema = Schema(
        version=1,
        tables=[
            {
                "name": "t",
                "rows": 10,
                "primary_key": {"columns": ["id"], "strategy": "sequence"},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "v", "type": "int", "invalid_ratio": 0.1},
                ],
            }
        ],
    )
    errors = validate_with_registry(schema, ValidationContext(generators=generators))
    assert any("invalid_ratio" in error.message for error in errors)
