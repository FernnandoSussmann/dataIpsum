"""Testes das estratégias de chave primária (DD-01 §B.3.1, §B.6)."""

from __future__ import annotations

import re

import numpy as np

from dataipsum.relations import keys

_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def test_sequence_pk_com_start_e_step() -> None:
    indices = np.arange(5, dtype=np.int64)
    result = keys.sequence_pk(indices, start=10, step=3)
    assert result.tolist() == [10, 13, 16, 19, 22]


def test_sequence_overflow_detectado() -> None:
    assert keys.sequence_overflows(rows=2, start=2**63 - 1, step=1) is True
    assert keys.sequence_overflows(rows=2, start=1, step=1) is False


def test_seeded_int_pk_e_unico_e_na_faixa() -> None:
    rows = 5000
    indices = np.arange(rows, dtype=np.int64)
    result = keys.seeded_int_pk(indices, rows, table_seed=123, start=1)
    assert sorted(result.tolist()) == list(range(1, rows + 1))


def test_seeded_int_pk_e_deterministico() -> None:
    indices = np.arange(100, dtype=np.int64)
    first = keys.seeded_int_pk(indices, 100, table_seed=7, start=1)
    second = keys.seeded_int_pk(indices, 100, table_seed=7, start=1)
    assert (first == second).all()


def test_seeded_uuid_pk_e_unico_em_1e6() -> None:
    rows = 1_000_000
    indices = np.arange(rows, dtype=np.int64)
    result = keys.seeded_uuid_pk(indices, table_seed=42)
    values = result.to_pylist()
    assert len(set(values)) == rows


def test_seeded_uuid_pk_tem_versao_4_e_variante_rfc4122() -> None:
    indices = np.arange(2000, dtype=np.int64)
    result = keys.seeded_uuid_pk(indices, table_seed=1)
    values = result.to_pylist()
    assert all(_UUID_PATTERN.match(value) for value in values)


def test_seeded_uuid_pk_e_deterministico() -> None:
    indices = np.arange(50, dtype=np.int64)
    first = keys.seeded_uuid_pk(indices, table_seed=9).to_pylist()
    second = keys.seeded_uuid_pk(indices, table_seed=9).to_pylist()
    assert first == second
