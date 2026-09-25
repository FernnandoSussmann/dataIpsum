"""Trilha C (DD-01): provedores LLM e classificador de toxicidade."""

from __future__ import annotations

from dataipsum.llm.providers import anthropic_available
from dataipsum.llm.providers.anthropic import AnthropicProvider
from dataipsum.llm.providers.ollama import OllamaProvider
from dataipsum.llm.providers.openai_compatible import OpenAICompatibleProvider
from dataipsum.llm.toxicity.detoxify_classifier import DetoxifyClassifier
from dataipsum.llm.toxicity.wordlist import WordlistClassifier
from dataipsum.registry import Registry


def register(registry: Registry) -> None:
    """Registra provedores LLM e classificadores de toxicidade (§C.4).

    `anthropic` só é registrado se o SDK oficial (extra `[anthropic]`) estiver instalado; sem
    ele, o `kind: anthropic` do schema fica indisponível e um erro claro aparece só quando o
    usuário tenta usá-lo (não aqui, no carregamento do registry).
    """
    registry.register_llm_provider("ollama", OllamaProvider)
    registry.register_llm_provider("openai_compatible", OpenAICompatibleProvider)
    if anthropic_available():
        registry.register_llm_provider("anthropic", AnthropicProvider)

    registry.register_toxicity("wordlist", WordlistClassifier)
    registry.register_toxicity("detoxify", DetoxifyClassifier)
