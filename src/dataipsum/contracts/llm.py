"""Contrato `LLMProvider` (DD-00 §3.5). Erros tipados em `dataipsum.errors`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMRequest:
    system: str
    prompt: str
    max_tokens: int
    temperature: float
    json_schema: dict[str, object] | None = None
    seed: int | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str
    finish_reason: str
    usage: dict[str, int] | None = None


class LLMProvider(Protocol):
    supports_json_schema: bool
    supports_seed: bool

    def complete(self, req: LLMRequest) -> LLMResponse: ...
