"""Classificador Detoxify `multilingual` (extra opcional `[toxicity]`, DD-01 §C.3.5).

Importado tardiamente: sem o extra instalado, `available()` devolve `False` e `score()` nunca é
chamado por `resolve_classifier` (`dataipsum.llm.toxicity`). Nenhum outro módulo da trilha C
importa `detoxify` no topo do arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _import_detoxify() -> Any:
    try:
        from detoxify import Detoxify
    except ImportError:
        return None
    return Detoxify


@dataclass
class DetoxifyClassifier:
    name: str = "detoxify"
    checkpoint: str = "multilingual"
    _model: Any = field(default=None, init=False, repr=False)

    def available(self) -> bool:
        return _import_detoxify() is not None

    def score(self, texts: list[str]) -> list[float]:
        if not texts:
            return []
        model = self._model_instance()
        predictions = model.predict(list(texts))
        return [float(value) for value in predictions["toxicity"]]

    def _model_instance(self) -> Any:
        if self._model is None:
            detoxify_cls = _import_detoxify()
            if detoxify_cls is None:
                raise RuntimeError(
                    "Detoxify não está instalado; instale o extra '[toxicity]' ou use "
                    "'resolve_classifier' para cair na lista de palavras."
                )
            self._model = detoxify_cls(self.checkpoint)
        return self._model
