"""Derivação de seeds e sorteio determinístico por célula (DD-00 §3.6).

Todo sorteio é uma função pura de `(seed_col, linha_global, slot)`, sem estado
sequencial: o mesmo chunk, reprocessado em qualquer worker, produz o mesmo
resultado, e qualquer linha é recalculável isoladamente a partir de
`(seed, tabela, índice)`. Este é o único módulo do pacote autorizado a ser
fonte de aleatoriedade: nenhum outro arquivo em `dataipsum` pode usar
`random`, `numpy.random` global ou `Faker.seed()` (teste de arquitetura em
`tests/core/unit/test_architecture_no_random.py`).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

_MASK64 = 0xFFFFFFFFFFFFFFFF

# Slots reservados (DD-00 §3.6, "Slots reservados").
NULL_SLOT: int = 0
INVALID_SLOT: int = 1
FIRST_FREE_SLOT: int = 2
LAST_FREE_SLOT: int = 63
FIRST_REJECTION_SLOT: int = 64

# Teto de tentativas da amostragem por rejeição de Lemire (`integers` acima de
# 2**53): cada tentativa além da primeira usa um slot crescente a partir de
# `FIRST_REJECTION_SLOT`. A chance de rejeição por tentativa é `span / 2**64`,
# então esse teto nunca é atingido em uso normal; ele existe só para não gerar
# um laço infinito se algo estiver incorreto a montante.
#
# DD-00 §3.6 diz que esse teto é "declarado pelo gerador"; aqui ele é uma
# constante fixa do módulo porque nenhum `Generator` real existe ainda
# (escopo da trilha A, DD-01). Quando um gerador precisar de um teto
# diferente, conectar a `Generator.draw_slots` (já existe no contrato,
# `contracts/generator.py`) em vez de mudar esta constante global.
MAX_REJECTION_ATTEMPTS: int = 64

# Faixas até este tamanho usam `uniform() * span` (perde precisão acima de
# 2**53 bits de mantissa do float64); faixas maiores usam a rejeição de Lemire
# diretamente sobre `draw_u64`.
_UNIFORM_SPAN_LIMIT = 2**53

_ADVANCE_CONSTANT = np.uint64(0x9E3779B97F4A7C15)
_SLOT_CONSTANT = np.uint64(0xD1B54A32D192ED03)


def derive(parent: int, label: str) -> int:
    """Deriva um `u64` filho a partir de `parent` e de um rótulo textual.

    `blake2b(parent.to_bytes(8, "little") + label.encode(), digest_size=8)`
    (DD-00 §3.6). Toda a hierarquia de seeds (`seed_table`, `seed_column`,
    `seed_chunk`, `seed_relation`, `seed_llm`) é construída chamando esta
    função com o rótulo apropriado.
    """
    parent_bytes = (parent & _MASK64).to_bytes(8, "little")
    digest = hashlib.blake2b(parent_bytes + label.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little")


def seed_table(root_seed: int, table: str) -> int:
    return derive(root_seed, f"t:{table}")


def seed_column(table_seed: int, column: str) -> int:
    return derive(table_seed, f"c:{column}")


def seed_chunk(column_seed: int, chunk_id: int) -> int:
    return derive(column_seed, f"k:{chunk_id}")


def seed_relation(table_seed: int, relation: str) -> int:
    return derive(table_seed, f"r:{relation}")


def seed_llm(column_seed: int, row: int) -> int:
    """Seed enviada ao LLM: independente de `chunk_size`, o que preserva a
    chave do cache LLM entre execuções (DD-00 §3.6, trilha C)."""
    return derive(column_seed, f"llm:{row}")


def mix(x: NDArray[np.uint64]) -> NDArray[np.uint64]:
    """Finalizador SplitMix64 (DD-00 §3.6): espalha os bits de um contador.

    Nomes de uma letra (`x`) são os do algoritmo documentado (§3.10).
    """
    with np.errstate(over="ignore"):
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return x ^ (x >> np.uint64(31))


def draw_u64(seed_col: int, rows: NDArray[np.int64], slot: int) -> NDArray[np.uint64]:
    """Sorteio bruto de 64 bits, vetorizado, puro em `(seed_col, rows, slot)`."""
    rows_u64 = rows.astype(np.uint64)
    with np.errstate(over="ignore"):
        seed_col_u64 = np.uint64(seed_col & _MASK64)
        slot_u64 = np.uint64(slot & _MASK64)
        counter = mix(seed_col_u64 + rows_u64 * _ADVANCE_CONSTANT)
        return mix(counter + slot_u64 * _SLOT_CONSTANT)


def uniform(seed_col: int, rows: NDArray[np.int64], slot: int) -> NDArray[np.float64]:
    """Float em `[0, 1)` a partir dos 53 bits mais significativos de `draw_u64`."""
    bits = draw_u64(seed_col, rows, slot)
    return (bits >> np.uint64(11)).astype(np.float64) * (2.0**-53)


def _widening_multiply(
    multiplicand: NDArray[np.uint64], multiplier: np.uint64
) -> tuple[NDArray[np.uint64], NDArray[np.uint64]]:
    """Produto de 128 bits de `multiplicand` (vetor) por `multiplier` (escalar).

    numpy não tem `uint128`; a decomposição em metades de 32 bits é a forma
    padrão de obter os 64 bits altos e baixos do produto sem estourar
    `uint64`. Usada pela rejeição de Lemire em `integers`.
    """
    mask32 = np.uint64(0xFFFFFFFF)
    with np.errstate(over="ignore"):
        left_lo = multiplicand & mask32
        left_hi = multiplicand >> np.uint64(32)
        right_lo = multiplier & mask32
        right_hi = multiplier >> np.uint64(32)

        lo_lo = left_lo * right_lo
        hi_lo = left_hi * right_lo
        lo_hi = left_lo * right_hi
        hi_hi = left_hi * right_hi

        cross = (lo_lo >> np.uint64(32)) + (hi_lo & mask32) + (lo_hi & mask32)
        low = ((cross & mask32) << np.uint64(32)) | (lo_lo & mask32)
        high = (
            hi_hi + (hi_lo >> np.uint64(32)) + (lo_hi >> np.uint64(32)) + (cross >> np.uint64(32))
        )
    return high, low


def _lemire_offsets(
    seed_col: int, rows: NDArray[np.int64], slot: int, span: int
) -> NDArray[np.int64]:
    """Deslocamentos em `[0, span)` sem viés de módulo (rejeição de Lemire).

    A primeira tentativa usa `slot`; as tentativas seguintes usam slots
    crescentes a partir de `FIRST_REJECTION_SLOT` (DD-00 §3.6, "Slots
    reservados"), até `MAX_REJECTION_ATTEMPTS`.
    """
    span_u64 = np.uint64(span)
    threshold = np.uint64((2**64 - span) % span)
    pending = np.ones(rows.shape[0], dtype=np.bool_)
    offsets = np.zeros(rows.shape[0], dtype=np.uint64)
    current_slot = slot
    for attempt in range(MAX_REJECTION_ATTEMPTS + 1):
        pending_indices = np.flatnonzero(pending)
        if pending_indices.size == 0:
            break
        candidate = draw_u64(seed_col, rows[pending_indices], current_slot)
        high, low = _widening_multiply(candidate, span_u64)
        accepted = low >= threshold
        offsets[pending_indices[accepted]] = high[accepted]
        pending[pending_indices[accepted]] = False
        current_slot = FIRST_REJECTION_SLOT + attempt
    if pending.any():
        raise RuntimeError(
            "amostragem por rejeição de Lemire excedeu o teto de "
            f"{MAX_REJECTION_ATTEMPTS} tentativas"
        )
    return offsets.astype(np.int64)


def integers(
    seed_col: int, rows: NDArray[np.int64], slot: int, lo: int, hi: int
) -> NDArray[np.int64]:
    """Inteiros em `[lo, hi)`.

    Até `2**53` de amplitude usa `lo + floor(uniform * (hi - lo))`; acima
    disso, `uniform` perderia precisão, então a amostra vem direto de
    `draw_u64` com rejeição de Lemire (DD-00 §3.6).
    """
    span = hi - lo
    if span <= 0:
        raise ValueError(f"integers requer hi > lo (recebido lo={lo}, hi={hi})")
    if span <= _UNIFORM_SPAN_LIMIT:
        offsets = np.floor(uniform(seed_col, rows, slot) * span).astype(np.int64)
        return (np.int64(lo) + offsets).astype(np.int64)
    return (np.int64(lo) + _lemire_offsets(seed_col, rows, slot, span)).astype(np.int64)


def choice(seed_col: int, rows: NDArray[np.int64], slot: int, n: int) -> NDArray[np.int64]:
    """Índice em `[0, n)`, delega a `integers`."""
    return integers(seed_col, rows, slot, 0, n)


def normal(seed_col: int, rows: NDArray[np.int64], slot: int) -> NDArray[np.float64]:
    """Normal padrão via Box-Muller, usando os slots `slot` e `slot + 1`.

    Só a componente cosseno é usada; a componente seno seria estatisticamente
    equivalente e descartá-la mantém a função simples de auditar.
    """
    smallest_positive_uniform = 2.0**-53
    radius_input = uniform(seed_col, rows, slot)
    angle_input = uniform(seed_col, rows, slot + 1)
    radius_input = np.where(radius_input == 0.0, smallest_positive_uniform, radius_input)
    radius = np.sqrt(-2.0 * np.log(radius_input))
    return (radius * np.cos(2.0 * np.pi * angle_input)).astype(np.float64)


@dataclass(frozen=True, eq=False)
class Draws:
    """Lote de sorteios para um conjunto de linhas globais (`rows`), não
    necessariamente contíguas. Cada método é O(1) por linha, independente do
    tamanho do chunk de onde `rows` veio (DD-00 §3.6)."""

    seed_col: int
    rows: NDArray[np.int64]

    def uniform(self, slot: int) -> NDArray[np.float64]:
        return uniform(self.seed_col, self.rows, slot)

    def integers(self, slot: int, lo: int, hi: int) -> NDArray[np.int64]:
        return integers(self.seed_col, self.rows, slot, lo, hi)

    def choice(self, slot: int, n: int) -> NDArray[np.int64]:
        return choice(self.seed_col, self.rows, slot, n)

    def normal(self, slot: int) -> NDArray[np.float64]:
        return normal(self.seed_col, self.rows, slot)


def random_seed() -> int:
    """Seed usada quando o schema não declara `seed` (DD-00 §3.6, "Seed
    ausente"): gravada no manifesto com `seed_source: "random"`."""
    return secrets.randbits(63)
