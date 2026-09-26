"""Guardrails de transporte e de saída não confiável do LLM (DD-01 §C.5.2, §C.5.3)."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from dataipsum.errors import LLMError

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 32

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_KEEP_CONTROL_CHARS = {"\n", "\t"}


class TransportSecurityError(LLMError):
    pass


class UnsafeResponseError(LLMError):
    pass


def _is_local_host(host: str) -> bool:
    return host in _LOCAL_HOSTS or "." not in host


def check_transport(base_url: str, *, allow_insecure_http: bool = False) -> None:
    """`anthropic`/`openai_compatible` com host não local exigem `https://` (§C.5.2).

    `http://` é aceito sem aviso para `localhost`, `127.0.0.1`, `::1` ou nomes de serviço sem
    ponto (ex.: `ollama` no compose). Fora disso, só com `allow_insecure_http=True`.
    """
    parts = urlsplit(base_url)
    if parts.scheme == "https":
        return
    if parts.scheme != "http":
        raise TransportSecurityError(f"esquema de transporte não suportado: '{parts.scheme}'")
    host = parts.hostname or ""
    if _is_local_host(host):
        return
    if allow_insecure_http:
        return
    raise TransportSecurityError(
        f"'{base_url}' usa http:// para um host não local ('{host}'); use https:// ou defina "
        "'allow_insecure_http: true' na configuração do provedor"
    )


def strip_control_characters(text: str) -> str:
    """Remove caracteres de controle da saída do LLM, exceto `\\n`/`\\t` (§C.5.3)."""
    return "".join(
        char for char in text if char in _KEEP_CONTROL_CHARS or not _is_control_char(char)
    )


def _is_control_char(char: str) -> bool:
    codepoint = ord(char)
    return codepoint < 0x20 or codepoint == 0x7F


def _check_json_depth(value: object, depth: int) -> None:
    if depth > MAX_JSON_DEPTH:
        raise UnsafeResponseError(
            f"JSON do provedor excede a profundidade máxima ({MAX_JSON_DEPTH})"
        )
    if isinstance(value, dict):
        for item in value.values():
            _check_json_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_json_depth(item, depth + 1)


def safe_json_loads(text: str) -> object:
    """`json.loads` sob limite de tamanho/profundidade (§C.5.3): resposta é dado não confiável."""
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise UnsafeResponseError(f"resposta do provedor excede {MAX_RESPONSE_BYTES} bytes")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UnsafeResponseError(f"resposta do provedor não é JSON válido: {exc}") from exc
    _check_json_depth(value, 0)
    return value
