"""Garante que os módulos de contrato só com Protocol são importáveis (DD-00 §3.5)."""

from __future__ import annotations

from dataipsum.contracts import toxicity


class FakeToxicity:
    name = "fake"

    def score(self, texts: list[str]) -> list[float]:
        return [0.0 for _ in texts]

    def available(self) -> bool:
        return True


def test_fake_toxicity_implementa_o_protocolo_estruturalmente() -> None:
    classifier: toxicity.ToxicityClassifier = FakeToxicity()
    assert classifier.score(["a", "b"]) == [0.0, 0.0]
    assert classifier.available() is True
