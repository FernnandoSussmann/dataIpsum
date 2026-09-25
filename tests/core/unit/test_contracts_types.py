"""Testes de `LogicalType` e `to_arrow_type` (DD-00 §3.5)."""

from __future__ import annotations

import pyarrow as pa
import pytest

from dataipsum.contracts import types as t


@pytest.mark.parametrize(
    ("logical_type", "expected"),
    [
        (t.string(120), pa.string()),
        (t.text(), pa.string()),
        (t.char(3), pa.string()),
        (t.int64(), pa.int64()),
        (t.int32(), pa.int32()),
        (t.float64(), pa.float64()),
        (t.decimal(10, 2), pa.decimal128(10, 2)),
        (t.boolean(), pa.bool_()),
        (t.date(), pa.date32()),
        (t.time(), pa.time32("ms")),
        (t.timestamp(), pa.timestamp("ms", tz=None)),
        (t.timestamp(tz=True), pa.timestamp("ms", tz="UTC")),
        (t.uuid(), pa.string()),
        (t.json(), pa.string()),
    ],
)
def test_to_arrow_type_mapeia_cada_kind(logical_type: t.LogicalType, expected: pa.DataType) -> None:
    assert t.to_arrow_type(logical_type) == expected


def test_to_arrow_type_array_aninhado() -> None:
    logical_type = t.array(t.int64(), max_items=10)
    assert t.to_arrow_type(logical_type) == pa.list_(pa.int64())


def test_to_arrow_type_array_sem_item_falha() -> None:
    logical_type = t.LogicalType(kind="array")
    with pytest.raises(ValueError, match="item"):
        t.to_arrow_type(logical_type)


def test_to_arrow_type_kind_desconhecido_falha() -> None:
    logical_type = t.LogicalType(kind="boolean")
    object.__setattr__(logical_type, "kind", "inexistente")
    with pytest.raises(ValueError, match="desconhecido"):
        t.to_arrow_type(logical_type)
