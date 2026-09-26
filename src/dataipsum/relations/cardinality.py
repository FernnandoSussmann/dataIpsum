"""Cardinalidade de linhas filhas por pai (DD-01 §B.3.4).

`sample` é puro em `(spec, seed_col, parent_indices)`: por pai `j`, o número
de filhos é sorteado com `Draws(seed_relation(filho, "card"))` usando
`row = j`, sem consultar dados já gerados. `UniformCardinality` é açúcar de
legibilidade para `RangeCardinality`; produz exatamente o mesmo resultado
(DD-01 §B.3.4).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from dataipsum import seeds
from dataipsum.relations import _zipf

MAX_CARDINALITY = 1_000_000
MAX_THREAD_CARDINALITY = 1_000


@dataclass(frozen=True)
class FixedCardinality:
    k: int

    def __post_init__(self) -> None:
        if self.k < 0:
            raise ValueError(f"cardinalidade 'fixed' requer k >= 0 (recebido {self.k})")


@dataclass(frozen=True)
class RangeCardinality:
    min: int
    max: int

    def __post_init__(self) -> None:
        if not (0 <= self.min <= self.max):
            raise ValueError(
                f"cardinalidade 'range' requer 0 <= min <= max (recebido min={self.min}, "
                f"max={self.max})"
            )


@dataclass(frozen=True)
class UniformCardinality:
    mean: int
    spread: int

    def __post_init__(self) -> None:
        if self.mean - self.spread < 0:
            raise ValueError(
                f"cardinalidade 'uniform' requer mean - spread >= 0 (recebido mean={self.mean}, "
                f"spread={self.spread})"
            )

    def as_range(self) -> RangeCardinality:
        return RangeCardinality(self.mean - self.spread, self.mean + self.spread)


@dataclass(frozen=True)
class ZipfCardinality:
    s: float
    min: int = 1
    max: int = 1

    def __post_init__(self) -> None:
        if self.s <= 0:
            raise ValueError(f"cardinalidade 'zipf' requer s > 0 (recebido {self.s})")
        if not (0 <= self.min <= self.max):
            raise ValueError(
                f"cardinalidade 'zipf' requer 0 <= min <= max (recebido min={self.min}, "
                f"max={self.max})"
            )


CardinalitySpec = FixedCardinality | RangeCardinality | UniformCardinality | ZipfCardinality


def max_allowed_for(spec: CardinalitySpec) -> int:
    if isinstance(spec, FixedCardinality):
        return spec.k
    if isinstance(spec, RangeCardinality):
        return spec.max
    if isinstance(spec, UniformCardinality):
        return spec.mean + spec.spread
    if isinstance(spec, ZipfCardinality):
        return spec.max
    raise TypeError(f"cardinalidade desconhecida: {spec!r}")


def sample(
    spec: CardinalitySpec, seed_col: int, parent_indices: NDArray[np.int64]
) -> NDArray[np.int64]:
    """Número de filhos por pai, em `parent_indices`. Vetorizado, sem estado."""
    if isinstance(spec, FixedCardinality):
        return np.full(parent_indices.shape, spec.k, dtype=np.int64)
    if isinstance(spec, UniformCardinality):
        return sample(spec.as_range(), seed_col, parent_indices)
    if isinstance(spec, RangeCardinality):
        return seeds.integers(seed_col, parent_indices, 0, spec.min, spec.max + 1)
    if isinstance(spec, ZipfCardinality):
        span = spec.max - spec.min + 1
        rank0 = _zipf.exact_rank(seed_col, parent_indices, 0, spec.s, span)
        return spec.min + rank0
    raise TypeError(f"cardinalidade desconhecida: {spec!r}")
