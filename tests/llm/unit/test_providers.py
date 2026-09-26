"""Testes dos provedores com `httpx.MockTransport` (DD-01 §C.6). Nenhuma chamada de rede real."""

from __future__ import annotations

import json

import httpx
import pytest

from dataipsum.contracts.llm import LLMRequest
from dataipsum.errors import ProviderBadResponse, ProviderRateLimited, ProviderUnavailable
from dataipsum.llm.providers.ollama import OllamaProvider
from dataipsum.llm.providers.openai_compatible import OpenAICompatibleProvider
from dataipsum.llm.security import TransportSecurityError

_REQUEST = LLMRequest(
    system="responda em pt-BR",
    prompt="escreva um post",
    max_tokens=128,
    temperature=0.0,
    seed=99,
    json_schema={"type": "object"},
)


def _client_with(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- ollama -------------------------------------------------------------


def test_ollama_monta_request_correto() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": "texto gerado"}, "done": True})

    provider = OllamaProvider(model="llama3.1:8b", client=_client_with(handler))
    response = provider.complete(_REQUEST)

    assert response.text == "texto gerado"
    assert captured["url"] == "http://localhost:11434/api/chat"
    body = captured["body"]
    assert body["model"] == "llama3.1:8b"
    assert body["options"]["seed"] == 99
    assert body["format"] == {"type": "object"}
    assert body["messages"][0] == {"role": "system", "content": "responda em pt-BR"}


def test_ollama_mapeia_429_com_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"}, text="rate limited")

    provider = OllamaProvider(model="m", client=_client_with(handler))
    with pytest.raises(ProviderRateLimited) as exc_info:
        provider.complete(_REQUEST)
    assert exc_info.value.retry_after == 7.0  # type: ignore[attr-defined]


def test_ollama_mapeia_5xx_para_provider_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="fora do ar")

    provider = OllamaProvider(model="m", client=_client_with(handler))
    with pytest.raises(ProviderUnavailable):
        provider.complete(_REQUEST)


def test_ollama_mapeia_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout", request=request)

    provider = OllamaProvider(model="m", client=_client_with(handler))
    with pytest.raises(ProviderUnavailable):
        provider.complete(_REQUEST)


def test_ollama_resposta_malformada_e_provider_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sem_message": True})

    provider = OllamaProvider(model="m", client=_client_with(handler))
    with pytest.raises(ProviderBadResponse):
        provider.complete(_REQUEST)


def test_ollama_resposta_vazia_e_provider_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "   "}})

    provider = OllamaProvider(model="m", client=_client_with(handler))
    with pytest.raises(ProviderBadResponse):
        provider.complete(_REQUEST)


def test_ollama_exige_https_para_host_nao_local() -> None:
    with pytest.raises(TransportSecurityError):
        OllamaProvider(model="m", base_url="http://api.exemplo.com")


# --- openai_compatible ----------------------------------------------------


def test_openai_compatible_monta_request_correto() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "texto"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 42},
            },
        )

    provider = OpenAICompatibleProvider(
        model="meu-modelo",
        base_url="http://localhost:8000",
        client=_client_with(handler),
    )
    response = provider.complete(_REQUEST)

    assert response.text == "texto"
    assert captured["url"] == "http://localhost:8000/v1/chat/completions"
    body = captured["body"]
    assert body["model"] == "meu-modelo"
    assert body["seed"] == 99
    assert body["response_format"]["type"] == "json_schema"
    assert captured["auth"] is None


def test_openai_compatible_usa_a_variavel_de_ambiente_da_chave(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINHA_CHAVE", "SEGREDO123")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    provider = OpenAICompatibleProvider(
        model="m",
        base_url="http://localhost:8000",
        api_key_env="MINHA_CHAVE",
        client=_client_with(handler),
    )
    provider.complete(_REQUEST)
    assert captured["auth"] == "Bearer SEGREDO123"
    # A chave nunca fica guardada como atributo do provedor (só o NOME da env var).
    assert "SEGREDO123" not in repr(provider)


def test_openai_compatible_repr_nunca_contem_a_chave() -> None:
    provider = OpenAICompatibleProvider(
        model="m", base_url="http://localhost:8000", api_key_env="ALGUMA_VAR"
    )
    assert "ALGUMA_VAR" in repr(provider) or provider.api_key_env == "ALGUMA_VAR"
    assert "SEGREDO" not in repr(provider)


def test_openai_compatible_mapeia_429_5xx_e_timeout() -> None:
    def handler_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="limitado")

    provider = OpenAICompatibleProvider(
        model="m", base_url="http://localhost:8000", client=_client_with(handler_429)
    )
    with pytest.raises(ProviderRateLimited):
        provider.complete(_REQUEST)

    def handler_5xx(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="erro interno")

    provider = OpenAICompatibleProvider(
        model="m", base_url="http://localhost:8000", client=_client_with(handler_5xx)
    )
    with pytest.raises(ProviderUnavailable):
        provider.complete(_REQUEST)

    def handler_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout", request=request)

    provider = OpenAICompatibleProvider(
        model="m", base_url="http://localhost:8000", client=_client_with(handler_timeout)
    )
    with pytest.raises(ProviderUnavailable):
        provider.complete(_REQUEST)


def test_openai_compatible_exige_https_para_host_nao_local() -> None:
    with pytest.raises(TransportSecurityError):
        OpenAICompatibleProvider(model="m", base_url="http://api.exemplo.com")


def test_openai_compatible_aceita_http_com_allow_insecure() -> None:
    OpenAICompatibleProvider(model="m", base_url="http://api.exemplo.com", allow_insecure_http=True)


# --- anthropic (só a parte que não exige o SDK instalado) -----------------


def test_anthropic_indisponivel_sem_extra() -> None:
    from dataipsum.llm.providers.anthropic import AnthropicProvider

    try:
        import anthropic  # noqa: F401

        pytest.skip("extra '[anthropic]' instalado; este teste cobre a ausência do SDK")
    except ImportError:
        pass

    provider = AnthropicProvider(model="claude-3", api_key_env="ANTHROPIC_API_KEY")
    with pytest.raises(ProviderUnavailable):
        provider.complete(_REQUEST)


def test_anthropic_exige_https_para_host_nao_local() -> None:
    from dataipsum.llm.providers.anthropic import AnthropicProvider

    with pytest.raises(TransportSecurityError):
        AnthropicProvider(model="claude-3", base_url="http://api.exemplo.com")
