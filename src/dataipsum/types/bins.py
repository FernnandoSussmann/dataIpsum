"""Bandeiras e BINs de cartão de crédito (DD-01 A.3), carregados de `data/bins.yaml`."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import cast

import yaml


@dataclass(frozen=True)
class BinPrefix:
    """Um BIN literal (`"4"`) ou uma faixa numérica (`"2221-2720"`, mesma largura)."""

    start: str
    end: str

    @property
    def width(self) -> int:
        return len(self.start)

    @property
    def is_range(self) -> bool:
        return self.start != self.end


@dataclass(frozen=True)
class Brand:
    name: str
    length: int
    prefixes: tuple[BinPrefix, ...]


def _parse_prefix(raw: str) -> BinPrefix:
    if "-" in raw:
        start, end = raw.split("-", 1)
        return BinPrefix(start=start, end=end)
    return BinPrefix(start=raw, end=raw)


@lru_cache(maxsize=1)
def default_brands() -> dict[str, Brand]:
    with (
        resources.files("dataipsum.types.data")
        .joinpath("bins.yaml")
        .open("r", encoding="utf-8") as handle
    ):
        raw = yaml.safe_load(handle)
    return {
        name: Brand(
            name=name,
            length=spec["length"],
            prefixes=tuple(_parse_prefix(prefix) for prefix in spec["prefixes"]),
        )
        for name, spec in raw["brands"].items()
    }


def with_extra_bins(
    brands: dict[str, Brand], extra_bins: tuple[dict[str, object], ...]
) -> dict[str, Brand]:
    """Acrescenta `params.extra_bins` às bandeiras conhecidas (ou cria uma nova bandeira)."""
    result = dict(brands)
    for extra in extra_bins:
        brand_name = str(extra["brand"])
        prefix = _parse_prefix(str(extra["prefix"]))
        length = int(cast("int | str", extra["length"]))
        existing = result.get(brand_name)
        if existing is None:
            result[brand_name] = Brand(name=brand_name, length=length, prefixes=(prefix,))
        else:
            result[brand_name] = Brand(
                name=brand_name, length=existing.length, prefixes=(*existing.prefixes, prefix)
            )
    return result
