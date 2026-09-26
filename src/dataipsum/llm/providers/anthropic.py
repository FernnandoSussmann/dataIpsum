"""Provedor `anthropic` (extra opcional `[anthropic]`, SDK oficial, DD-01 §C.3.1).

Importado tardiamente: sem o extra instalado, `llm.register` simplesmente não registra este
provedor (`dataipsum.llm.providers.anthropic_available`); tentar usá-lo sem o SDK levanta
`ProviderUnavailable` com uma mensagem clara, em vez de um `ImportError` cru.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from dataipsum.contracts.llm import LLMRequest, LLMResponse
from dataipsum.errors import (
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderRefusal,
    ProviderUnavailable,
)
from dataipsum.llm.security import check_transport, strip_control_characters

_PROVIDER_KIND = "anthropic"
DEFAULT_BASE_URL = "https://api.anthropic.com"


def _import_anthropic() -> Any:
    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError:
        return None
    return anthropic


@dataclass
class AnthropicProvider:
    model: str
    base_url: str = DEFAULT_BASE_URL
    timeout_s: float = 120.0
    allow_insecure_http: bool = False
    api_key_env: str | None = None
    # Cliente `httpx` injetável em testes: repassado a `anthropic.Anthropic(http_client=...)`.
    http_client: Any = None
    supports_json_schema: bool = field(default=False, init=False)
    supports_seed: bool = field(default=False, init=False)
    _sdk: Any = field(default=None, init=False, repr=False)
    _client: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        check_transport(self.base_url, allow_insecure_http=self.allow_insecure_http)

    def _sdk_client(self) -> Any:
        if self._client is not None:
            return self._client
        self._sdk = _import_anthropic()
        if self._sdk is None:
            raise ProviderUnavailable(
                f"{_PROVIDER_KIND}: SDK 'anthropic' não instalado; instale o extra '[anthropic]'"
            )
        api_key = os.environ.get(self.api_key_env, "") if self.api_key_env else ""
        self._client = self._sdk.Anthropic(
            api_key=api_key,
            base_url=self.base_url,
            timeout=self.timeout_s,
            http_client=self.http_client,
        )
        return self._client

    def complete(self, req: LLMRequest) -> LLMResponse:
        client = self._sdk_client()
        sdk = self._sdk
        try:
            response = client.messages.create(
                model=self.model,
                system=req.system,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                messages=[{"role": "user", "content": req.prompt}],
            )
        except sdk.RateLimitError as exc:
            raise _rate_limited(exc) from exc
        except sdk.APIStatusError as exc:
            raise _mapped_status_error(exc) from exc
        except sdk.APIConnectionError as exc:
            raise ProviderUnavailable(f"{_PROVIDER_KIND}: erro de transporte: {exc}") from exc

        if getattr(response, "stop_reason", None) == "refusal":
            raise ProviderRefusal(f"{_PROVIDER_KIND}: recusa do provedor")
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        if not text:
            raise ProviderBadResponse(f"{_PROVIDER_KIND}: resposta vazia")
        usage = None
        if getattr(response, "usage", None) is not None:
            usage = {
                "input_tokens": int(response.usage.input_tokens),
                "output_tokens": int(response.usage.output_tokens),
            }
        return LLMResponse(
            text=strip_control_characters(text),
            finish_reason=str(response.stop_reason),
            usage=usage,
        )


def _rate_limited(exc: Any) -> ProviderRateLimited:
    error = ProviderRateLimited(f"{_PROVIDER_KIND}: rate limited: {exc}")
    response = getattr(exc, "response", None)
    header_value = response.headers.get("retry-after") if response is not None else None
    error.retry_after = float(header_value) if header_value else None  # type: ignore[attr-defined]
    return error


def _mapped_status_error(exc: Any) -> ProviderUnavailable | ProviderBadResponse:
    status = getattr(exc, "status_code", 500)
    message = f"{_PROVIDER_KIND}: HTTP {status}: {exc}"
    if status >= 500:
        return ProviderUnavailable(message)
    return ProviderBadResponse(message)
