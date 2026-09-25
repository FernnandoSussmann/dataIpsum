"""Contrato `ToxicityClassifier` (DD-00 §3.5)."""

from __future__ import annotations

from typing import Protocol


class ToxicityClassifier(Protocol):
    name: str

    def score(self, texts: list[str]) -> list[float]:
        """Score de toxicidade por texto, no intervalo [0, 1]."""
        ...

    def available(self) -> bool: ...
