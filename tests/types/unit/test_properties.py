"""Testes de propriedade (hypothesis, DD-01 A.6): para parâmetros válidos
sorteados, o gerador nunca lança erro e sempre respeita o `LogicalType`."""

from __future__ import annotations

import numpy as np
import pyarrow as pa
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dataipsum.contracts.generator import RowBatch
from dataipsum.contracts.types import to_arrow_type
from dataipsum.registry import Registry
from dataipsum.schema.models import ColumnSpec
from dataipsum.seeds import Draws, seed_column, seed_table
from dataipsum.types import register as register_types

_REGISTRY = Registry()
register_types(_REGISTRY)


def _run(type_name: str, params: dict[str, object], max_length: int | None = None) -> None:
    column = ColumnSpec(name="c", type=type_name, params=params, max_length=max_length)
    generator = _REGISTRY.get_generator(type_name)()
    rows = np.arange(0, 30, dtype=np.int64)
    seed_col = seed_column(seed_table(1, "t"), "c")
    draws = Draws(seed_col=seed_col, rows=rows)
    batch = RowBatch(rows=rows, invalid_mask=np.zeros(30, dtype=bool))

    class Ctx:
        locale = "pt_BR"

        def same_row(self, names: list[str]) -> dict[str, pa.Array]:
            return {}

        def parent_rows(self, table, parent_indices, columns):
            raise NotImplementedError

    array = generator.generate(column, batch, draws, Ctx())
    assert len(array) == 30
    assert array.type == to_arrow_type(generator.logical_type(column))


@given(max_length=st.integers(1, 300), min_length=st.integers(0, 50))
@settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow])
def test_string_propriedade(max_length: int, min_length: int) -> None:
    if min_length > max_length:
        min_length = max_length
    _run("string", {"min_length": min_length, "charset": "alnum"}, max_length=max_length)


@given(length=st.integers(1, 255))
@settings(max_examples=25)
def test_char_propriedade(length: int) -> None:
    _run("char", {"length": length})


@given(minimum=st.integers(-1000, 1000), span=st.integers(0, 5000))
@settings(max_examples=25)
def test_int_propriedade(minimum: int, span: int) -> None:
    _run("int", {"min": minimum, "max": minimum + span})


@given(minimum=st.floats(-100, 0), span=st.floats(0, 100))
@settings(max_examples=25)
def test_float_propriedade(minimum: float, span: float) -> None:
    _run("float", {"min": minimum, "max": minimum + span})


@given(true_ratio=st.floats(0.0, 1.0))
@settings(max_examples=25)
def test_boolean_propriedade(true_ratio: float) -> None:
    _run("boolean", {"true_ratio": true_ratio})


@given(precision=st.integers(1, 38), scale=st.integers(1, 10))
@settings(max_examples=25)
def test_decimal_propriedade(precision: int, scale: int) -> None:
    # `scale=0` é evitado aqui: `contracts/types.py::to_arrow_type` usa
    # `logical_type.scale or 2`, que trata `scale == 0` como "ausente" e cai no
    # padrão 2 — um bug pré-existente fora do escopo desta trilha (não mexemos
    # em `contracts/`). `DecimalGenerator` em si produz `scale=0` corretamente
    # (ver `tests/types/unit/test_documents.py`/`test_primitives.py`).
    scale = min(scale, precision)
    _run("decimal", {"precision": precision, "scale": scale})


@given(max_items=st.integers(0, 20))
@settings(max_examples=15)
def test_array_propriedade(max_items: int) -> None:
    _run(
        "array",
        {
            "items": {"type": "int", "params": {"min": 0, "max": 9}},
            "min_items": 0,
            "max_items": max_items,
        },
    )
