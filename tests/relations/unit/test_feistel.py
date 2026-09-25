"""Testes de `feistel.perm` (DD-01 §B.6)."""

from __future__ import annotations

import numpy as np
import pytest

from dataipsum.relations import feistel


@pytest.mark.parametrize("n", [1, 2, 3, 1000, 2**20 + 7])
def test_perm_e_bijecao(n: int) -> None:
    x = np.arange(n, dtype=np.int64)
    y = feistel.perm(x, n, key=12345)
    assert sorted(y.tolist()) == list(range(n))


@pytest.mark.parametrize("n", [1, 2, 3, 1000])
def test_perm_e_deterministica(n: int) -> None:
    x = np.arange(n, dtype=np.int64)
    first = feistel.perm(x, n, key=42)
    second = feistel.perm(x, n, key=42)
    assert (first == second).all()


def test_chaves_diferentes_geram_permutacoes_diferentes() -> None:
    x = np.arange(1000, dtype=np.int64)
    a = feistel.perm(x, 1000, key=1)
    b = feistel.perm(x, 1000, key=2)
    assert not (a == b).all()


def test_vetorizacao_com_chaves_por_elemento() -> None:
    x = np.array([0, 0, 0], dtype=np.int64)
    keys = np.array([1, 2, 3], dtype=np.int64)
    result = feistel.perm(x, 100, keys)
    scalar_results = [feistel.perm(0, 100, int(k)) for k in keys]
    assert result.tolist() == scalar_results
    assert len(set(result.tolist())) == 3


def test_perm_aceita_escalar_e_devolve_escalar() -> None:
    result = feistel.perm(5, 1000, key=1)
    assert isinstance(result, int)
    assert 0 <= result < 1000


def test_perm_com_n_igual_a_um_e_a_identidade_nula() -> None:
    result = feistel.perm(np.array([0], dtype=np.int64), 1, key=999)
    assert result.tolist() == [0]


def test_perm_rejeita_n_nao_positivo() -> None:
    with pytest.raises(ValueError, match="n > 0"):
        feistel.perm(np.array([0], dtype=np.int64), 0, key=1)
