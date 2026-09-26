"""Registry de locales da trilha A (DD-01 A.3, "Locale").

Um locale empacota os recursos usados pelos geradores com regra nacional
(`nome_proprio`, `email`): listas de nomes pt-BR (snapshot do Faker, ver
`types/data/names_pt_BR.json`) e a lista de palavras pt-BR usada pelo
`charset: lorem` de `string`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache, lru_cache
from importlib import resources
from typing import cast

from dataipsum.registry import Registry

PT_BR = "pt_BR"


@dataclass(frozen=True)
class Locale:
    name: str
    first_names_f: tuple[str, ...]
    first_names_m: tuple[str, ...]
    last_names: tuple[str, ...]
    lorem_words: tuple[str, ...]

    @property
    def first_names_any(self) -> tuple[str, ...]:
        return self.first_names_f + self.first_names_m


@cache
def _read_json(filename: str) -> object:
    with (
        resources.files("dataipsum.types.data")
        .joinpath(filename)
        .open("r", encoding="utf-8") as handle
    ):
        return json.load(handle)


@lru_cache(maxsize=1)
def pt_br_locale() -> Locale:
    names = _read_json("names_pt_BR.json")
    assert isinstance(names, dict)
    lorem_words = _read_json("lorem_pt_BR.json")
    assert isinstance(lorem_words, list)
    return Locale(
        name=PT_BR,
        first_names_f=tuple(names["first_names_f"]),
        first_names_m=tuple(names["first_names_m"]),
        last_names=tuple(names["last_names"]),
        lorem_words=tuple(lorem_words),
    )


def register(registry: Registry) -> None:
    registry.register_locale(PT_BR, pt_br_locale())


def resolve_locale(locales: Mapping[str, object], name: str) -> Locale:
    """Busca o locale `name` no mapa vivo do registry (DD-01 A.3, "Locale").

    Recebe o próprio mapa do registry (não uma cópia): plugins que registram
    locales depois desta trilha ainda são vistos, porque a busca é feita em
    tempo de geração, não em tempo de registro. O valor é sempre um `Locale`
    (built-in ou de um plugin); a assinatura usa `object` porque é assim que
    `Registry.locales` é tipado (DD-00 §3.4).
    """
    try:
        return cast(Locale, locales[name])
    except KeyError:
        known = ", ".join(sorted(locales)) or "nenhum"
        raise KeyError(f"locale desconhecido: '{name}'. Registrados: {known}") from None
