"""Estratégias de chave primária (DD-01 §B.3.1).

O valor de uma coluna de PK vem sempre da estratégia; o gerador do tipo nunca
é chamado para ela. Cada função é O(1) por índice (recálculo local, §B.3.7).
"""

from __future__ import annotations

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from dataipsum import seeds
from dataipsum.relations import feistel

_MASK64 = 0xFFFFFFFFFFFFFFFF
_VERSION_CLEAR_MASK = np.uint64(0xFFFFFFFFFFFF0FFF)
_VERSION_4_BITS = np.uint64(0x4000)
_VARIANT_10_BITS = np.uint64(0b10 << 62)
_LOW_62_BITS_MASK = np.uint64((1 << 62) - 1)


def sequence_overflows(rows: int, start: int, step: int) -> bool:
    return rows > 0 and start + step * (rows - 1) >= 2**63


def sequence_pk(indices: NDArray[np.int64], start: int, step: int) -> NDArray[np.int64]:
    return (start + indices.astype(np.int64) * step).astype(np.int64)


def seeded_int_pk(
    indices: NDArray[np.int64], rows: int, table_seed: int, start: int
) -> NDArray[np.int64]:
    key = seeds.derive(table_seed, "pk:seeded_int")
    permuted = np.asarray(feistel.perm(indices, rows, key), dtype=np.int64)
    return (start + permuted).astype(np.int64)


def seeded_uuid_pk(indices: NDArray[np.int64], table_seed: int) -> pa.Array:
    """UUIDv4-compatível: altos = `mix(seed_table ^ i)` (versão 4); baixos =
    `(i XOR k) & (2^62-1)` (variante RFC 4122 `10`), com `k = derive(seed_table, "uuid")`.

    Injetivo em `i` porque `i < 2^62` é garantido pelo limite de linhas por tabela.
    """
    i_u64 = indices.astype(np.uint64)
    high = seeds.mix(np.uint64(table_seed & _MASK64) ^ i_u64)
    high = (high & _VERSION_CLEAR_MASK) | _VERSION_4_BITS
    k = np.uint64(seeds.derive(table_seed, "uuid") & _MASK64)
    low = ((i_u64 ^ k) & _LOW_62_BITS_MASK) | _VARIANT_10_BITS
    values = [
        f"{(h >> 32) & 0xFFFFFFFF:08x}-{(h >> 16) & 0xFFFF:04x}-{h & 0xFFFF:04x}-"
        f"{(low_value >> 48) & 0xFFFF:04x}-{low_value & 0xFFFFFFFFFFFF:012x}"
        for h, low_value in zip(high.tolist(), low.tolist(), strict=True)
    ]
    return pa.array(values, type=pa.string())
