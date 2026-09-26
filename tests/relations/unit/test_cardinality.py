"""Testes de `cardinality.sample` (DD-01 §B.3.4, §B.6)."""

from __future__ import annotations

import numpy as np
import pytest

from dataipsum.relations import cardinality


def test_fixed_e_sempre_o_mesmo_valor() -> None:
    parents = np.arange(1000, dtype=np.int64)
    result = cardinality.sample(
        cardinality.FixedCardinality(k=7), seed_col=1, parent_indices=parents
    )
    assert (result == 7).all()


def test_fixed_rejeita_k_negativo() -> None:
    with pytest.raises(ValueError, match="k >= 0"):
        cardinality.FixedCardinality(k=-1)


def test_range_fica_dentro_dos_limites() -> None:
    parents = np.arange(5000, dtype=np.int64)
    result = cardinality.sample(
        cardinality.RangeCardinality(min=2, max=8), seed_col=1, parent_indices=parents
    )
    assert result.min() >= 2
    assert result.max() <= 8


def test_range_rejeita_min_maior_que_max() -> None:
    with pytest.raises(ValueError, match="min <= max"):
        cardinality.RangeCardinality(min=5, max=2)


def test_uniform_e_equivalente_a_range() -> None:
    parents = np.arange(2000, dtype=np.int64)
    uniform_result = cardinality.sample(
        cardinality.UniformCardinality(mean=5, spread=2), seed_col=99, parent_indices=parents
    )
    range_result = cardinality.sample(
        cardinality.RangeCardinality(min=3, max=7), seed_col=99, parent_indices=parents
    )
    assert (uniform_result == range_result).all()


def test_uniform_rejeita_spread_maior_que_mean() -> None:
    with pytest.raises(ValueError, match="mean - spread"):
        cardinality.UniformCardinality(mean=2, spread=5)


def test_zipf_media_empirica_perto_da_teorica() -> None:
    parents = np.arange(200_000, dtype=np.int64)
    spec = cardinality.ZipfCardinality(s=2.0, min=1, max=20)
    result = cardinality.sample(spec, seed_col=1, parent_indices=parents)
    categories = np.arange(1, 20 + 1, dtype=np.float64)
    weights = categories ** (-spec.s)
    theoretical_mean = float((categories * weights).sum() / weights.sum())
    empirical_mean = float(result.mean())
    assert abs(empirical_mean - theoretical_mean) < 0.05


def test_zipf_respeita_limites() -> None:
    parents = np.arange(5000, dtype=np.int64)
    spec = cardinality.ZipfCardinality(s=1.5, min=3, max=9)
    result = cardinality.sample(spec, seed_col=5, parent_indices=parents)
    assert result.min() >= 3
    assert result.max() <= 9


def test_zipf_rejeita_s_nao_positivo() -> None:
    with pytest.raises(ValueError, match="s > 0"):
        cardinality.ZipfCardinality(s=0, min=1, max=5)


def test_max_allowed_for() -> None:
    assert cardinality.max_allowed_for(cardinality.FixedCardinality(k=3)) == 3
    assert cardinality.max_allowed_for(cardinality.RangeCardinality(min=1, max=9)) == 9
    assert cardinality.max_allowed_for(cardinality.UniformCardinality(mean=5, spread=2)) == 7
    assert cardinality.max_allowed_for(cardinality.ZipfCardinality(s=1, min=1, max=42)) == 42
