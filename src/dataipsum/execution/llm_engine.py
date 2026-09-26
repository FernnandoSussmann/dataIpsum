"""Monta o `LLMEngine` (trilha C) a partir do `Schema`/`Registry` (integração S5).

`LLMConfig` (DD-00 §3.3) ainda não tem uma seção `llm.toxicity` (§C.3.5 do DD-01 propõe
`{classifier, threshold}`, mas o modelo Pydantic de `dataipsum.schema.models.LLMConfig` só
define `default_provider`/`providers`/`retry`); enquanto essa lacuna não é fechada por um PR de
mudança de contrato, esta função usa o classificador `"auto"` (lista de palavras + Detoxify,
quando disponível, com aviso de fallback) e o limiar padrão `0.5` (§C.3.5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from dataipsum.contracts.llm import LLMProvider
from dataipsum.errors import LLMError
from dataipsum.llm.cache import DiskCache
from dataipsum.llm.filler import LLMEngine
from dataipsum.llm.retry import RetryPolicy
from dataipsum.llm.toxicity import resolve_classifier

if TYPE_CHECKING:
    from pathlib import Path

    from dataipsum.llm.filler import ToxicityClassifierLike
    from dataipsum.registry import Registry
    from dataipsum.schema.models import LLMProviderConfig, Schema

_DEFAULT_TOXICITY_THRESHOLD = 0.5


def build_llm_engine(
    schema: Schema, registry: Registry, *, cache_dir: Path | None = None
) -> LLMEngine | None:
    """`None` quando o schema não usa LLM (`schema.llm is None`)."""
    if schema.llm is None:
        return None

    providers = {name: _build_provider(registry, cfg) for name, cfg in schema.llm.providers.items()}
    retry = schema.llm.retry
    return LLMEngine(
        providers=providers,
        toxicity_classifier=cast("ToxicityClassifierLike", resolve_classifier("auto")),
        toxicity_threshold=_DEFAULT_TOXICITY_THRESHOLD,
        retry_policy=RetryPolicy(
            max_attempts=retry.max_attempts,
            base_delay_s=retry.base_delay_s,
            max_delay_s=retry.max_delay_s,
        ),
        cache=DiskCache(cache_dir) if cache_dir is not None else None,
    )


def _build_provider(registry: Registry, cfg: LLMProviderConfig) -> LLMProvider:
    provider_cls = registry.llm_providers.get(cfg.kind)
    if provider_cls is None:
        raise LLMError(f"provedor LLM desconhecido: '{cfg.kind}'")
    kwargs: dict[str, object] = {"model": cfg.model, "timeout_s": cfg.timeout_s}
    if cfg.base_url is not None:
        kwargs["base_url"] = cfg.base_url
    if cfg.api_key_env is not None:
        kwargs["api_key_env"] = cfg.api_key_env
    return cast("type[LLMProvider]", provider_cls)(**kwargs)
