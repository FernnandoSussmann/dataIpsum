"""Testes de guardrails de transporte e de saída não confiável (DD-01 §C.5, §C.6)."""

from __future__ import annotations

import json

import pytest

from dataipsum.llm.security import (
    MAX_RESPONSE_BYTES,
    TransportSecurityError,
    UnsafeResponseError,
    check_transport,
    safe_json_loads,
    strip_control_characters,
)


def test_https_e_sempre_aceito() -> None:
    check_transport("https://api.exemplo.com")


def test_http_local_e_aceito_sem_flag() -> None:
    check_transport("http://localhost:11434")
    check_transport("http://127.0.0.1:11434")
    check_transport("http://ollama:11434")  # nome de serviço sem ponto


def test_http_nao_local_e_rejeitado() -> None:
    with pytest.raises(TransportSecurityError):
        check_transport("http://api.exemplo.com")


def test_http_nao_local_e_aceito_com_allow_insecure_http() -> None:
    check_transport("http://api.exemplo.com", allow_insecure_http=True)


def test_strip_control_characters_mantem_newline_e_tab() -> None:
    text = "linha1\nlinha2\tfim\x00\x07"
    assert strip_control_characters(text) == "linha1\nlinha2\tfim"


def test_safe_json_loads_aceita_json_valido() -> None:
    assert safe_json_loads('{"a": 1}') == {"a": 1}


def test_safe_json_loads_rejeita_acima_do_limite() -> None:
    huge = json.dumps({"a": "x" * (MAX_RESPONSE_BYTES + 10)})
    with pytest.raises(UnsafeResponseError):
        safe_json_loads(huge)


def test_safe_json_loads_rejeita_profundidade_excessiva() -> None:
    nested = "1"
    for _ in range(64):
        nested = f"[{nested}]"
    with pytest.raises(UnsafeResponseError):
        safe_json_loads(nested)


def test_safe_json_loads_rejeita_json_malformado() -> None:
    with pytest.raises(UnsafeResponseError):
        safe_json_loads("{invalido")
