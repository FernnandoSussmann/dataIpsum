"""Testes de toxicidade (DD-01 §C.6): lista de palavras, combinação OR, `auto` sem extra."""

from __future__ import annotations

import logging

import pytest

from dataipsum.llm.toxicity import CombinedClassifier, is_offensive, resolve_classifier
from dataipsum.llm.toxicity.wordlist import WordlistClassifier


def test_wordlist_casa_palavra_inteira_ignorando_acento_e_caixa() -> None:
    classifier = WordlistClassifier()
    assert classifier.score(["Que MERDA de dia"]) == [1.0]
    assert classifier.score(["Que porcaria"])[0] == 0.0


def test_wordlist_nao_casa_substring_de_outra_palavra() -> None:
    classifier = WordlistClassifier()
    # "burrocratico" não é a palavra "burro".
    assert classifier.score(["processo burrocratico e lento"])[0] == 0.0


def test_wordlist_ignora_pontuacao_ao_redor_da_palavra() -> None:
    classifier = WordlistClassifier()
    assert classifier.score(["que porra!"])[0] == 1.0


class _AlwaysScore:
    def __init__(self, name: str, value: float) -> None:
        self.name = name
        self._value = value

    def available(self) -> bool:
        return True

    def score(self, texts: list[str]) -> list[float]:
        return [self._value for _ in texts]


class _Unavailable:
    name = "indisponivel"

    def available(self) -> bool:
        return False

    def score(self, texts: list[str]) -> list[float]:  # pragma: no cover - nunca chamado
        raise AssertionError("classificador indisponível não deveria ser chamado")


def test_combined_classifier_e_or_entre_classificadores() -> None:
    combined = CombinedClassifier(classifiers=(_AlwaysScore("a", 0.0), _AlwaysScore("b", 0.9)))
    assert combined.score(["qualquer texto"]) == [0.9]


def test_combined_classifier_ignora_indisponivel() -> None:
    combined = CombinedClassifier(classifiers=(_Unavailable(), _AlwaysScore("b", 0.3)))
    assert combined.score(["texto"]) == [0.3]
    assert combined.available() is True


def test_is_offensive_por_limiar() -> None:
    assert is_offensive(0.5, threshold=0.5) is True
    assert is_offensive(0.49, threshold=0.5) is False


def test_resolve_classifier_wordlist_explicito() -> None:
    classifier = resolve_classifier("wordlist")
    assert isinstance(classifier, WordlistClassifier)


def test_resolve_classifier_auto_sem_extra_cai_para_wordlist_com_aviso(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="dataipsum.llm.toxicity"):
        classifier = resolve_classifier("auto", offline=False)
    assert isinstance(classifier, WordlistClassifier)
    assert any("lista de palavras" in record.getMessage() for record in caplog.records)


def test_resolve_classifier_offline_cai_para_wordlist_com_aviso(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="dataipsum.llm.toxicity"):
        classifier = resolve_classifier("auto", offline=True)
    assert isinstance(classifier, WordlistClassifier)
    assert any("DATAIPSUM_OFFLINE" in record.getMessage() for record in caplog.records)
