"""Rank de uma Zipf truncada, para cardinalidade e FK não dirigente (DD-01 §B.3.3, §B.3.4).

`exact_rank` usa a CDF exata (população ≤ `EXACT_CDF_LIMIT`); `approx_rank`
usa a inversa contínua de uma lei de potência truncada, aproximação
documentada para populações maiores (DD-01 §B.3.3). `rank` escolhe entre as
duas pelo tamanho da população.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from dataipsum import seeds

EXACT_CDF_LIMIT = 1_000_000


def exact_rank(
    seed_col: int, rows: NDArray[np.int64], slot: int, s: float, count: int
) -> NDArray[np.int64]:
    """Rank em `[0, count)` pela CDF exata de uma Zipf(s) sobre `count` categorias."""
    categories = np.arange(1, count + 1, dtype=np.float64)
    probability_mass = categories ** (-s)
    cumulative = np.cumsum(probability_mass)
    cumulative /= cumulative[-1]
    draw = seeds.uniform(seed_col, rows, slot)
    rank0 = np.searchsorted(cumulative, draw, side="right")
    return np.clip(rank0, 0, count - 1).astype(np.int64)


def approx_rank(
    seed_col: int, rows: NDArray[np.int64], slot: int, s: float, count: int
) -> NDArray[np.int64]:
    """Rank aproximado via inversa contínua de uma lei de potência truncada em `[1, count]`.

    Trata a Zipf discreta como uma Pareto truncada contínua (ignora a soma
    harmônica exata), aproximação necessária quando `count` é grande demais
    para montar a CDF exata em memória (DD-01 §B.3.3).
    """
    draw = seeds.uniform(seed_col, rows, slot)
    n = float(count)
    if abs(s - 1.0) < 1e-9:
        value = n**draw
    else:
        exponent = 1.0 - s
        value = (1.0 - draw * (1.0 - n**exponent)) ** (1.0 / exponent)
    rank0 = np.round(value).astype(np.int64) - 1
    return np.clip(rank0, 0, count - 1)


def rank(
    seed_col: int, rows: NDArray[np.int64], slot: int, s: float, count: int
) -> NDArray[np.int64]:
    if count <= EXACT_CDF_LIMIT:
        return exact_rank(seed_col, rows, slot, s, count)
    return approx_rank(seed_col, rows, slot, s, count)
