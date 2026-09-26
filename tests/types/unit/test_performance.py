"""A-02 (DD-01 A.8): mede (sem falhar) o tempo de 10^6 linhas por tipo. A meta
de desempenho ainda não foi definida pelo usuário; este teste só registra."""

from __future__ import annotations

import time

import numpy as np
import pyarrow as pa
import pytest

from dataipsum.contracts.generator import RowBatch
from dataipsum.seeds import Draws, seed_column, seed_table

_ROW_COUNT = 1_000_000

_TYPES: list[tuple[str, dict[str, object], int | None]] = [
    ("string", {"charset": "alnum"}, 40),
    ("char", {"length": 10}, None),
    ("int", {}, None),
    ("float", {}, None),
    ("decimal", {"precision": 10, "scale": 2}, None),
    ("boolean", {}, None),
    ("date", {}, None),
    ("time", {}, None),
    ("timestamp", {}, None),
    ("uuid", {}, None),
    ("cpf", {}, None),
    ("rg", {}, None),
    ("cartao_credito", {}, None),
    ("nome_proprio", {}, None),
    ("email", {}, None),
]


class _Ctx:
    locale = "pt_BR"

    def same_row(self, names: list[str]) -> dict[str, pa.Array]:
        return {}

    def parent_rows(self, table: str, parent_indices, columns: list[str]) -> dict[str, pa.Array]:
        raise NotImplementedError


@pytest.mark.slow
@pytest.mark.parametrize(("type_name", "params", "max_length"), _TYPES)
def test_desempenho_10_6_linhas(registry, column_factory, type_name, params, max_length) -> None:
    column = column_factory(type_name, params=params, max_length=max_length)
    generator = registry.get_generator(type_name)()
    rows = np.arange(_ROW_COUNT, dtype=np.int64)
    seed_col = seed_column(seed_table(1, "perf"), type_name)
    draws = Draws(seed_col=seed_col, rows=rows)
    batch = RowBatch(rows=rows, invalid_mask=np.zeros(_ROW_COUNT, dtype=bool))

    start = time.perf_counter()
    array = generator.generate(column, batch, draws, _Ctx())
    elapsed = time.perf_counter() - start

    assert len(array) == _ROW_COUNT
    print(f"\n[A-02] {type_name}: {elapsed:.3f}s para {_ROW_COUNT} linhas")
