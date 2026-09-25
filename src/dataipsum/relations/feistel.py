"""Permutação Feistel com cycle-walking (DD-01 §B.3.2).

Bijeção vetorizada de `[0, n)` em `[0, n)`, com chave por elemento opcional.
Usada em `seeded_int`, na cobertura `one_to_one`, na escolha de participantes
de thread e na amostragem sem reposição do N:N (DD-01 §B.3.2).
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from dataipsum.seeds import mix

_MASK64 = 0xFFFFFFFFFFFFFFFF
_ROUNDS = 4
_ROUND_CONSTANT = 0x9E3779B97F4A7C15

# Domínio pleno de um round Feistel é 2^(2h) ≥ n; com h = ceil(bits(n)/2), o
# domínio nunca passa de 4n (DD-01 §B.3.2), então a caminhada de ciclo converge
# em poucas iterações. Este teto só existe para nunca gerar um laço infinito se
# `n`/`key` estiverem incoerentes a montante (mesmo papel de
# `seeds.MAX_REJECTION_ATTEMPTS`).
MAX_CYCLE_WALK_ITERATIONS = 1000


def _half_width_bits(n: int) -> int:
    if n <= 1:
        return 1
    return math.ceil((n - 1).bit_length() / 2)


def _feistel_round(
    x: NDArray[np.uint64], h: int, mask: np.uint64, key: NDArray[np.uint64]
) -> NDArray[np.uint64]:
    left = x >> np.uint64(h)
    right = x & mask
    for round_index in range(_ROUNDS):
        round_key = key ^ np.uint64((round_index * _ROUND_CONSTANT) & _MASK64)
        feistel_output = mix(right ^ round_key) & mask
        left, right = right, left ^ feistel_output
    return (left << np.uint64(h)) | right


def perm(
    x: int | NDArray[np.int64],
    n: int,
    key: int | NDArray[np.int64] | NDArray[np.uint64],
) -> int | NDArray[np.int64]:
    """Bijeção de `[0, n)` em `[0, n)`, determinística em `(x, n, key)`.

    `x` e `key` aceitam escalar ou array numpy; quando `key` é array, cada
    elemento de `x` usa sua própria chave (vetorização com chaves por
    elemento, DD-01 §B.6).
    """
    scalar_input = np.ndim(x) == 0
    x_arr = np.atleast_1d(np.asarray(x, dtype=np.int64))
    if n <= 0:
        raise ValueError(f"perm requer n > 0 (recebido {n})")
    if n == 1:
        result = np.zeros_like(x_arr)
        return int(result[0]) if scalar_input else result

    h = _half_width_bits(n)
    mask = np.uint64((1 << h) - 1)
    key_values = (
        np.full(x_arr.shape, key, dtype=np.uint64)
        if np.ndim(key) == 0
        else np.asarray(key, dtype=np.uint64)
    )
    current = x_arr.astype(np.uint64) & np.uint64((1 << (2 * h)) - 1)
    pending = np.ones(current.shape[0], dtype=np.bool_)
    n_u64 = np.uint64(n)
    iterations = 0
    while pending.any():
        if iterations > MAX_CYCLE_WALK_ITERATIONS:
            raise RuntimeError(
                f"perm excedeu o teto de {MAX_CYCLE_WALK_ITERATIONS} iterações de cycle-walking"
            )
        pending_indices = np.flatnonzero(pending)
        current[pending_indices] = _feistel_round(
            current[pending_indices], h, mask, key_values[pending_indices]
        )
        pending[pending_indices] = current[pending_indices] >= n_u64
        iterations += 1

    result = current.astype(np.int64)
    return int(result[0]) if scalar_input else result
