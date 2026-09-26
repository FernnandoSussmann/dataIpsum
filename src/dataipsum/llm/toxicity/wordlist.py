"""Classificador "leve" por lista de palavras pt-BR (DD-01 §C.3.5). Sempre ativo."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

_WORDLIST_PATH = Path(__file__).parent / "wordlists" / "pt_BR.txt"
_PUNCTUATION = ".,!?;:\"'()[]{}«»…-"


def normalize(text: str) -> str:
    """Minúsculas e sem acentos (NFKD sem marcas de combinação), para casar palavra inteira."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _load_wordlist(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return frozenset(normalize(line) for line in lines if line and not line.startswith("#"))


@dataclass
class WordlistClassifier:
    name: str = "wordlist"
    words: frozenset[str] = field(default_factory=lambda: _load_wordlist(_WORDLIST_PATH))

    def available(self) -> bool:
        return True

    def score(self, texts: list[str]) -> list[float]:
        return [1.0 if self._matches(text) else 0.0 for text in texts]

    def _matches(self, text: str) -> bool:
        tokens = normalize(text).split()
        stripped = (token.strip(_PUNCTUATION) for token in tokens)
        return any(token in self.words for token in stripped if token)
