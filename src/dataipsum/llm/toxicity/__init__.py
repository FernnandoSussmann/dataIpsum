"""Classificadores de toxicidade (DD-01 §C.3.5): lista de palavras + Detoxify opcional."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from dataipsum.llm.toxicity.detoxify_classifier import DetoxifyClassifier
from dataipsum.llm.toxicity.wordlist import WordlistClassifier

logger = logging.getLogger("dataipsum.llm.toxicity")

ClassifierKind = str  # "auto" | "wordlist" | "detoxify", validado na camada de schema/config.

__all__ = [
    "CombinedClassifier",
    "DetoxifyClassifier",
    "WordlistClassifier",
    "is_offensive",
    "resolve_classifier",
]


@dataclass
class CombinedClassifier:
    """OR entre classificadores disponíveis: score final é o máximo entre eles (§C.3.5)."""

    classifiers: tuple[object, ...] = field(default_factory=tuple)
    name: str = "auto"

    def available(self) -> bool:
        return any(classifier.available() for classifier in self.classifiers)  # type: ignore[attr-defined]

    def score(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        per_classifier = [
            classifier.score(texts)  # type: ignore[attr-defined]
            for classifier in self.classifiers
            if classifier.available()  # type: ignore[attr-defined]
        ]
        if not per_classifier:
            return [0.0 for _ in texts]
        return [max(values) for values in zip(*per_classifier, strict=True)]


def is_offensive(score: float, threshold: float) -> bool:
    return score >= threshold


def resolve_classifier(kind: str, *, offline: bool | None = None) -> object:
    """Resolve `llm.toxicity.classifier` ("auto" | "wordlist" | "detoxify") numa instância.

    `auto` usa os dois se o extra `[toxicity]` estiver instalado e `DATAIPSUM_OFFLINE` não
    estiver ativo; senão cai para a lista de palavras com um aviso (§C.3.5, §C.5 item 8).
    """
    wordlist = WordlistClassifier()
    if kind == "wordlist":
        return wordlist
    if kind == "detoxify":
        return DetoxifyClassifier()
    is_offline = (os.environ.get("DATAIPSUM_OFFLINE") == "1") if offline is None else offline
    if is_offline:
        logger.warning(
            "DATAIPSUM_OFFLINE=1: classificador de toxicidade usa só a lista de palavras pt-BR."
        )
        return wordlist
    detoxify = DetoxifyClassifier()
    if not detoxify.available():
        logger.warning(
            "Extra 'toxicity' (Detoxify) não instalado: classificador de toxicidade usa só a "
            "lista de palavras pt-BR."
        )
        return wordlist
    return CombinedClassifier(classifiers=(wordlist, detoxify))
