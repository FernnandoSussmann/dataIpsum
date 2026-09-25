"""Provedor `openai_compatible` (vLLM, LM Studio etc.): `POST {base_url}/v1/chat/completions`."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from dataipsum.contracts.llm import LLMRequest, LLMResponse
from dataipsum.errors import ProviderBadResponse, ProviderUnavailable
from dataipsum.llm.providers.base import raise_for_mapped_status, require_non_empty_text
from dataipsum.llm.security import (
    UnsafeResponseError,
    check_transport,
    safe_json_loads,
    strip_control_characters,
)

_PROVIDER_KIND = "openai_compatible"


@dataclass
class OpenAICompatibleProvider:
    model: str
    base_url: str
    timeout_s: float = 120.0
    allow_insecure_http: bool = False
    api_key_env: str | None = None
    supports_json_schema: bool = True
    client: httpx.Client | None = None
    supports_seed: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        check_transport(self.base_url, allow_insecure_http=self.allow_insecure_http)
        if self.client is None:
            self.client = httpx.Client(timeout=self.timeout_s)

    def _headers(self) -> dict[str, str]:
        if self.api_key_env is None:
            return {}
        api_key = os.environ.get(self.api_key_env)
        return {} if not api_key else {"Authorization": f"Bearer {api_key}"}

    def complete(self, req: LLMRequest) -> LLMResponse:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.prompt},
            ],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if req.seed is not None:
            payload["seed"] = req.seed
        if req.json_schema is not None and self.supports_json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "dataipsum_llm", "schema": req.json_schema},
            }

        client = self.client
        assert client is not None
        try:
            response = client.post(
                f"{self.base_url}/v1/chat/completions", json=payload, headers=self._headers()
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(f"{_PROVIDER_KIND}: timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{_PROVIDER_KIND}: erro de transporte: {exc}") from exc

        raise_for_mapped_status(response, provider_kind=_PROVIDER_KIND)
        try:
            body = safe_json_loads(response.text)
        except UnsafeResponseError as exc:
            raise ProviderBadResponse(f"{_PROVIDER_KIND}: resposta malformada: {exc}") from exc
        if not isinstance(body, dict):
            raise ProviderBadResponse(f"{_PROVIDER_KIND}: corpo da resposta não é um objeto JSON")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderBadResponse(f"{_PROVIDER_KIND}: resposta sem 'choices'")
        first_choice = choices[0]
        message = first_choice.get("message") if isinstance(first_choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderBadResponse(f"{_PROVIDER_KIND}: resposta sem 'message.content'")
        text = require_non_empty_text(
            strip_control_characters(content), provider_kind=_PROVIDER_KIND
        )
        finish_reason = str(first_choice.get("finish_reason") or "stop")
        usage_raw = body.get("usage")
        usage = (
            {key: int(value) for key, value in usage_raw.items() if isinstance(value, int)}
            if isinstance(usage_raw, dict)
            else None
        )
        return LLMResponse(text=text, finish_reason=finish_reason, usage=usage)
