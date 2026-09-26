"""Helpers de sorteio vetorizado usados pelos geradores da trilha A (DD-01 A.3).

Um gerador só pode usar `dataipsum.seeds` (via `Draws` ou diretamente) como
fonte de aleatoriedade. Alguns tipos (`string`, `json`, `array`, `nome_proprio`,
`email`) precisam de **vários** valores por linha (por posição de caractere,
por palavra, por campo) sem estourar os 62 slots livres (2..63, DD-00 §3.6).
`expand_rows` resolve isso combinando `(linha, posição)` num índice sintético
determinístico, que ainda é uma função pura de `(seed_col, linha, posição)`:
qualquer linha continua recalculável em O(1).
"""

from __future__ import annotations

from functools import reduce

import numpy as np
from numpy.typing import NDArray

from dataipsum.seeds import Draws, integers


def draw_matrix(draws: Draws, slot: int, width: int, lo: int, hi: int) -> NDArray[np.int64]:
    """Sorteia `width` inteiros em `[lo, hi)` por linha, devolvendo forma `(N, width)`."""
    rows = draws.rows
    positions = np.arange(width, dtype=np.int64)
    synthetic_rows = (rows[:, None] * np.int64(width) + positions[None, :]).reshape(-1)
    flat = integers(draws.seed_col, synthetic_rows, slot, lo, hi)
    return flat.reshape(rows.shape[0], width)


def truncate_to_lengths(values: NDArray[np.str_], lengths: NDArray[np.int64]) -> NDArray[np.str_]:
    """Trunca cada string de `values` ao comprimento correspondente em `lengths`.

    Percorre os comprimentos **distintos** (limitado pela faixa do parâmetro da
    coluna, não pelo número de linhas) e usa `astype` para o corte vetorizado
    de cada grupo, porque numpy não tem um "slice por linha" nativo.
    """
    result = np.empty(values.shape, dtype=values.dtype)
    for length in np.unique(lengths):
        mask = lengths == length
        if length == 0:
            result[mask] = ""
        else:
            result[mask] = values[mask].astype(f"<U{length}")
    return result


def index_matrix_to_chars(matrix: NDArray[np.int64], pool: str) -> NDArray[np.str_]:
    """Mapeia índices `(N, width)` para caracteres de `pool`: devolve uma matriz de
    caracteres `(N, width)`, ainda não unida em strings."""
    pool_array = np.array(list(pool), dtype="<U1")
    return pool_array[matrix]


def join_columns(char_matrix: NDArray[np.str_]) -> NDArray[np.str_]:
    """Une todas as colunas de uma matriz de caracteres `(N, width)` em strings `(N,)`."""
    width = char_matrix.shape[1]
    return reduce(
        np.char.add, (char_matrix[:, column] for column in range(1, width)), char_matrix[:, 0]
    )


def chars_from_pool(matrix: NDArray[np.int64], pool: str) -> NDArray[np.str_]:
    """Sorteia caracteres de `pool` a partir de índices `(N, width)`, já unidos em strings."""
    return join_columns(index_matrix_to_chars(matrix, pool))


def as_char_matrix(strings: NDArray[np.str_], width: int) -> NDArray[np.str_]:
    """Reinterpreta um array de strings de comprimento fixo `width` como matriz de
    caracteres `(N, width)`, sem cópia por linha (view de memória)."""
    return np.ascontiguousarray(strings).view("<U1").reshape(strings.shape[0], width)


def weighted_choice(draws: Draws, slot: int, weights: NDArray[np.float64]) -> NDArray[np.int64]:
    """Índice `[0, len(weights))` sorteado com probabilidade proporcional a `weights`."""
    cumulative = np.cumsum(weights) / weights.sum()
    sample = draws.uniform(slot)
    return np.clip(np.searchsorted(cumulative, sample, side="right"), 0, weights.shape[0] - 1)


def digits_of(values: NDArray[np.int64], width: int, base: int = 10) -> NDArray[np.int64]:
    """Dígitos de `values` na base `base`, zero-preenchidos à esquerda até `width`,
    mais significativo primeiro: `(N,) -> (N, width)`."""
    divisors = (np.int64(base) ** np.arange(width - 1, -1, -1)).astype(np.int64)
    return (values[:, None] // divisors[None, :]) % base


def format_layout(char_matrix: NDArray[np.str_], layout: list[int | str]) -> NDArray[np.str_]:
    """Monta uma string por linha a partir de `layout`: um `int` pega a coluna daquele
    índice de `char_matrix`; um `str` é um literal (separador) inserido em todas as linhas.

    O laço percorre `layout` (tamanho fixo do formato, independente de N), nunca as
    linhas: cada passo é uma operação vetorizada sobre as N linhas de uma vez.
    """
    rows = char_matrix.shape[0]
    pieces = (
        char_matrix[:, item]
        if isinstance(item, int)
        else np.full(rows, item, dtype=f"<U{len(item)}")
        for item in layout
    )
    return reduce(np.char.add, pieces)
