"""Fixtures compartilhadas dos testes da trilha A (DD-01)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pyarrow as pa
import pytest
from numpy.typing import NDArray

from dataipsum.contracts.generator import RowBatch
from dataipsum.registry import Registry
from dataipsum.schema.models import ColumnSpec
from dataipsum.seeds import Draws, seed_column, seed_table
from dataipsum.types import register as register_types


@dataclass
class FakeGenContext:
    """`GenContext` mínimo para testes de gerador isolado (DD-00 §3.5)."""

    locale: str = "pt_BR"
    _same_row: dict[str, pa.Array] = field(default_factory=dict)

    def same_row(self, column_names: list[str]) -> dict[str, pa.Array]:
        return {name: self._same_row[name] for name in column_names}

    def parent_rows(
        self, table: str, parent_indices: NDArray[np.int64], columns: list[str]
    ) -> dict[str, pa.Array]:
        raise NotImplementedError


@pytest.fixture(scope="session")
def registry() -> Registry:
    registry = Registry()
    register_types(registry)
    return registry


@pytest.fixture
def column_factory():
    return make_column


@pytest.fixture
def batch_factory():
    return make_batch


@pytest.fixture
def generate_column():
    return generate


@pytest.fixture
def gen_context_factory():
    return FakeGenContext


def make_column(
    type_name: str,
    *,
    params: dict[str, object] | None = None,
    max_length: int | None = None,
    null_ratio: float = 0.0,
    invalid_ratio: float = 0.0,
    format: str | None = None,  # noqa: A002 -- espelha o campo `ColumnSpec.format`
    locale: str | None = None,
    name: str = "coluna",
) -> ColumnSpec:
    return ColumnSpec(
        name=name,
        type=type_name,
        params=params or {},
        max_length=max_length,
        null_ratio=null_ratio,
        invalid_ratio=invalid_ratio,
        format=format,
        locale=locale,
    )


def make_batch(
    row_count: int,
    *,
    seed: int = 42,
    table: str = "tabela",
    column: str = "coluna",
    invalid_ratio: float = 0.0,
    first_row: int = 0,
) -> tuple[Draws, RowBatch]:
    rows = np.arange(first_row, first_row + row_count, dtype=np.int64)
    seed_col = seed_column(seed_table(seed, table), column)
    draws = Draws(seed_col=seed_col, rows=rows)
    invalid_mask = (
        Draws(seed_col=seed_col, rows=rows).uniform(1) < invalid_ratio
        if invalid_ratio > 0
        else np.zeros(row_count, dtype=np.bool_)
    )
    batch = RowBatch(rows=rows, invalid_mask=invalid_mask)
    return draws, batch


def generate(
    registry: Registry,
    column: ColumnSpec,
    *,
    row_count: int = 1000,
    seed: int = 42,
    invalid_ratio: float | None = None,
    ctx: FakeGenContext | None = None,
) -> pa.Array:
    draws, batch = make_batch(
        row_count,
        seed=seed,
        column=column.name,
        invalid_ratio=invalid_ratio or column.invalid_ratio,
    )
    generator = registry.get_generator(column.type)()
    return generator.generate(column, batch, draws, ctx or FakeGenContext())
