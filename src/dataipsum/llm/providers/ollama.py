"""Provedor `ollama` (padrão): `httpx` -> `POST {base_url}/api/chat` (DD-01 §C.3.1)."""

from __future__ import annotations

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

DEFAULT_BASE_URL = "http://localhost:11434"
_PROVIDER_KIND = "ollama"


@dataclass
class OllamaProvider:
    model: str
    base_url: str = DEFAULT_BASE_URL
    timeout_s: float = 120.0
    allow_insecure_http: bool = False
    client: httpx.Client | None = None
    supports_json_schema: bool = field(default=True, init=False)
    supports_seed: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        check_transport(self.base_url, allow_insecure_http=self.allow_insecure_http)
        if self.client is None:
            self.client = httpx.Client(timeout=self.timeout_s)

    def complete(self, req: LLMRequest) -> LLMResponse:
        options: dict[str, object] = {"temperature": req.temperature, "num_predict": req.max_tokens}
        if req.seed is not None:
            options["seed"] = req.seed
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.prompt},
            ],
            "stream": False,
            "options": options,
        }
        if req.json_schema is not None:
            payload["format"] = req.json_schema

        client = self.client
        assert client is not None
        try:
            response = client.post(f"{self.base_url}/api/chat", json=payload)
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
        message = body.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderBadResponse(f"{_PROVIDER_KIND}: resposta sem 'message.content'")
        text = require_non_empty_text(
            strip_control_characters(content), provider_kind=_PROVIDER_KIND
        )
        usage = None
        if isinstance(body.get("eval_count"), int):
            usage = {"output_tokens": int(body["eval_count"])}
        finish_reason = "stop" if body.get("done", True) else "length"
        return LLMResponse(text=text, finish_reason=finish_reason, usage=usage)
