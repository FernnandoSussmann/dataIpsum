"""Helpers compartilhados pelos transportes HTTP dos provedores (DD-01 §C.3.1)."""

from __future__ import annotations

import httpx

from dataipsum.errors import ProviderBadResponse, ProviderRateLimited, ProviderUnavailable
from dataipsum.llm.security import UnsafeResponseError, safe_json_loads

MAX_TEXT_PREVIEW = 200


def retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def raise_for_mapped_status(response: httpx.Response, *, provider_kind: str) -> None:
    """Mapeia 429/5xx/outros erros HTTP para os erros tipados do contrato (§C.3.1)."""
    if response.status_code == 429:
        error = ProviderRateLimited(
            f"{provider_kind}: HTTP 429 ({response.text[:MAX_TEXT_PREVIEW]!r})"
        )
        error.retry_after = retry_after_seconds(response)  # type: ignore[attr-defined]
        raise error
    if response.status_code >= 500:
        raise ProviderUnavailable(
            f"{provider_kind}: HTTP {response.status_code} ({response.text[:MAX_TEXT_PREVIEW]!r})"
        )
    if response.status_code >= 400:
        raise ProviderBadResponse(
            f"{provider_kind}: HTTP {response.status_code} ({response.text[:MAX_TEXT_PREVIEW]!r})"
        )


def request_json(
    client: httpx.Client, url: str, payload: dict[str, object], *, provider_kind: str
) -> object:
    try:
        response = client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise ProviderUnavailable(f"{provider_kind}: timeout ao chamar '{url}'") from exc
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(
            f"{provider_kind}: erro de transporte ao chamar '{url}': {exc}"
        ) from exc
    raise_for_mapped_status(response, provider_kind=provider_kind)
    try:
        return safe_json_loads(response.text)
    except UnsafeResponseError as exc:
        raise ProviderBadResponse(f"{provider_kind}: resposta malformada: {exc}") from exc


def require_non_empty_text(text: str, *, provider_kind: str) -> str:
    if not text.strip():
        raise ProviderBadResponse(f"{provider_kind}: resposta vazia")
    return text
