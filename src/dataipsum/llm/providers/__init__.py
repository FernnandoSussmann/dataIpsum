"""Provedores `LLMProvider` (DD-01 §C.3.1): `ollama`, `openai_compatible` e `anthropic`."""

from __future__ import annotations

from dataipsum.llm.providers.anthropic import AnthropicProvider, _import_anthropic
from dataipsum.llm.providers.ollama import OllamaProvider
from dataipsum.llm.providers.openai_compatible import OpenAICompatibleProvider

__all__ = [
    "AnthropicProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "anthropic_available",
]


def anthropic_available() -> bool:
    return _import_anthropic() is not None
