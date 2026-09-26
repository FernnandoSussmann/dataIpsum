"""Conteúdo de threads (`thread.llm`, DD-01 §C.3.8): JSON estruturado com fallback."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from dataipsum import seeds
from dataipsum.contracts.llm import LLMRequest
from dataipsum.errors import LLMError, SchemaError, ValidationError
from dataipsum.llm import security
from dataipsum.llm.filler import (
    LLMEngine,
    OnFailure,
    ToxicityMode,
    _float_param,
    _int_param,
    _on_failure_param,
    _optional_int_param,
    _optional_str_param,
    _toxicity_param,
    default_template,
    max_tokens_for,
    truncate_on_word_boundary,
    with_length_instruction,
)
from dataipsum.llm.template import parse_template, render
from dataipsum.llm.toxicity import is_offensive

HISTORY_MAX_MESSAGES = 20
HISTORY_MAX_BYTES = 8 * 1024


@dataclass(frozen=True)
class ThreadLLMConfig:
    provider: str
    prompt: str | None
    system: str | None
    toxicity: ToxicityMode
    toxicity_ratio: float | None
    on_failure: OnFailure
    max_regenerations: int
    max_length: int | None


def thread_llm_config(
    thread_block: Mapping[str, object] | None, *, default_provider: str
) -> ThreadLLMConfig:
    """Lê `thread.llm` (§C.3.8). `mode`/`pool_size` não são aceitos: threads usam só `unique`."""
    llm_block_raw = (thread_block or {}).get("llm")
    llm_block: Mapping[str, object] = llm_block_raw if isinstance(llm_block_raw, dict) else {}
    if "mode" in llm_block or "pool_size" in llm_block:
        raise SchemaError(
            [
                ValidationError(
                    path="thread.llm",
                    message=(
                        "'mode'/'pool_size' não são permitidos em 'thread.llm'; threads usam "
                        "sempre o modo 'unique'"
                    ),
                )
            ]
        )
    return ThreadLLMConfig(
        provider=str(llm_block.get("provider", default_provider)),
        prompt=_optional_str_param(llm_block, "prompt"),
        system=_optional_str_param(llm_block, "system"),
        toxicity=_toxicity_param(llm_block),
        toxicity_ratio=_float_param(llm_block, "toxicity_ratio"),
        on_failure=_on_failure_param(llm_block),
        max_regenerations=_int_param(llm_block, "max_regenerations", 3),
        max_length=_optional_int_param(llm_block, "max_length"),
    )


@dataclass(frozen=True)
class ThreadMessage:
    seq: int
    autor_label: str


@dataclass(frozen=True)
class ThreadOutcome:
    status: Literal["done", "pending_llm"]
    texts: list[str | None]
    is_offensive: list[bool]
    is_placeholder: list[bool]
    used_fallback: bool


def _parse_structured_messages(text: str, expected: int) -> list[str] | None:
    try:
        payload = security.safe_json_loads(text)
    except security.UnsafeResponseError:
        return None
    if not isinstance(payload, dict):
        return None
    mensagens = payload.get("mensagens")
    if not isinstance(mensagens, list) or len(mensagens) < expected:
        return None
    trimmed = mensagens[:expected]
    texts: list[str] = []
    for item in trimmed:
        if not isinstance(item, dict):
            return None
        texto = item.get("texto")
        if not isinstance(texto, str) or not texto.strip():
            return None
        texts.append(security.strip_control_characters(texto))
    return texts


def _json_schema(expected: int) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "mensagens": {
                "type": "array",
                "minItems": expected,
                "items": {
                    "type": "object",
                    "properties": {
                        "seq": {"type": "integer"},
                        "texto": {"type": "string"},
                    },
                    "required": ["seq", "texto"],
                },
            }
        },
        "required": ["mensagens"],
    }


def _clip_history(lines: Sequence[str]) -> str:
    recent = list(lines[-HISTORY_MAX_MESSAGES:])
    joined = "\n".join(recent)
    encoded = joined.encode("utf-8")
    if len(encoded) <= HISTORY_MAX_BYTES:
        return joined
    return encoded[-HISTORY_MAX_BYTES:].decode("utf-8", errors="ignore")


class ThreadFiller:
    """`ThreadFiller.fill(chunk_ctx) -> (texto_array, flags)` (§C.4).

    Assim como `LLMColumnFiller`, o formato de `chunk_ctx` é decisão da trilha D; aqui a unidade
    de trabalho é explícita: o contexto do pai da thread (`subject_context`, para `{thread_id.col}`)
    e a lista ordenada de mensagens (`seq`, autor) que a trilha B já calculou.
    """

    def __init__(self, engine: LLMEngine) -> None:
        self._engine = engine

    def fill(
        self,
        config: ThreadLLMConfig,
        *,
        thread_seed: int,
        subject_context: Mapping[str, object],
        messages: Sequence[ThreadMessage],
        via_column: str = "thread_id",
    ) -> ThreadOutcome:
        """`via_column` é o nome da coluna `ref` desta tabela (`rows_from.via`, §C.3.8):
        o template usa `{<via_column>.coluna}` para navegar até o pai da thread, exatamente
        como qualquer outra referência (§C.3.2) — "thread_id" é só o padrão quando o chamador
        não informa o nome real."""
        count = len(messages)
        if count == 0:
            return ThreadOutcome("done", [], [], [], False)

        template_text = config.prompt or default_template("conversa")
        tokens = parse_template(template_text)
        prompt_body = render(tokens, same_row={}, parent_values={via_column: subject_context})
        order_note = "Ordem fixa dos autores por mensagem: " + ", ".join(
            f"{message.seq}:{message.autor_label}" for message in messages
        )
        max_tokens = max_tokens_for(config.max_length) * max(1, count // 4 + 1)

        used_fallback = False
        texts = self._try_structured(
            config, prompt_body, order_note, thread_seed, count, max_tokens
        )
        if texts is None:
            used_fallback = True
            texts = self._fill_message_by_message(config, prompt_body, thread_seed, messages)
        if texts is None:
            return ThreadOutcome(
                "pending_llm", [None] * count, [False] * count, [False] * count, used_fallback
            )

        return self._apply_toxicity(
            config, prompt_body, thread_seed, messages, texts, used_fallback
        )

    def _try_structured(
        self,
        config: ThreadLLMConfig,
        prompt_body: str,
        order_note: str,
        thread_seed: int,
        count: int,
        max_tokens: int,
    ) -> list[str] | None:
        prompt = with_length_instruction(
            f"{prompt_body}\n\n{order_note}\nGere exatamente {count} mensagens, em ordem.",
            config.max_length,
        )
        json_schema = _json_schema(count)
        for attempt in (0, 1):
            seed = thread_seed if attempt == 0 else _derive_retry_seed(thread_seed, attempt)
            req = LLMRequest(
                system=config.system or "",
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=0.0,
                seed=seed,
                json_schema=json_schema,
            )
            try:
                text = self._engine.call(config.provider, req, seed_chunk=seed)
            except LLMError:
                return None
            parsed = _parse_structured_messages(text, count)
            if parsed is not None:
                return parsed
        return None

    def _fill_message_by_message(
        self,
        config: ThreadLLMConfig,
        prompt_body: str,
        thread_seed: int,
        messages: Sequence[ThreadMessage],
    ) -> list[str] | None:
        history: list[str] = []
        texts: list[str] = []
        for message in messages:
            prompt = with_length_instruction(
                f"{prompt_body}\n\nHistórico da conversa até agora:\n{_clip_history(history)}\n\n"
                f"Escreva só a mensagem {message.seq}, de {message.autor_label}.",
                config.max_length,
            )
            seed = _derive_message_seed(thread_seed, message.seq)
            req = LLMRequest(
                system=config.system or "",
                prompt=prompt,
                max_tokens=max_tokens_for(config.max_length),
                temperature=0.0,
                seed=seed,
            )
            try:
                text = self._engine.call(config.provider, req, seed_chunk=seed)
            except LLMError:
                return None
            texts.append(security.strip_control_characters(text))
            history.append(f"{message.autor_label}: {texts[-1]}")
        return texts

    def _apply_toxicity(
        self,
        config: ThreadLLMConfig,
        prompt_body: str,
        thread_seed: int,
        messages: Sequence[ThreadMessage],
        texts: list[str],
        used_fallback: bool,
    ) -> ThreadOutcome:
        offensive_flags: list[bool] = []
        for index, (message, text) in enumerate(zip(messages, texts, strict=True)):
            score = self._engine.toxicity_classifier.score([text])[0]
            offensive = is_offensive(score, self._engine.toxicity_threshold)
            if config.toxicity == "block" and offensive:
                regenerated = self._regenerate_clean(
                    config, prompt_body, thread_seed, message, texts
                )
                if regenerated is None:
                    count = len(messages)
                    return ThreadOutcome(
                        "pending_llm",
                        [None] * count,
                        [False] * count,
                        [False] * count,
                        used_fallback,
                    )
                texts[index] = regenerated
                offensive = False
            offensive_flags.append(offensive)
        final_texts: list[str | None] = [
            truncate_on_word_boundary(text, config.max_length)
            if config.max_length is not None
            else text
            for text in texts
        ]
        return ThreadOutcome(
            "done", final_texts, offensive_flags, [False for _ in messages], used_fallback
        )

    def _regenerate_clean(
        self,
        config: ThreadLLMConfig,
        prompt_body: str,
        thread_seed: int,
        message: ThreadMessage,
        texts: Sequence[str],
    ) -> str | None:
        history = list(texts[: message.seq - 1])
        for attempt in range(1, config.max_regenerations + 1):
            prompt = (
                f"{prompt_body}\n\nHistórico da conversa até agora:\n{_clip_history(history)}\n\n"
                f"Escreva só a mensagem {message.seq}, de {message.autor_label}, com linguagem "
                "apropriada."
            )
            seed = _derive_message_seed(thread_seed, message.seq, suffix=f"regen:{attempt}")
            req = LLMRequest(
                system=config.system or "",
                prompt=prompt,
                max_tokens=max_tokens_for(config.max_length),
                temperature=0.0,
                seed=seed,
            )
            try:
                text = self._engine.call(config.provider, req, seed_chunk=seed)
            except LLMError:
                return None
            score = self._engine.toxicity_classifier.score([text])[0]
            if not is_offensive(score, self._engine.toxicity_threshold):
                return security.strip_control_characters(text)
        return None


def _derive_retry_seed(thread_seed: int, attempt: int) -> int:
    return seeds.derive(thread_seed, f"retry:{attempt}")


def _derive_message_seed(thread_seed: int, seq: int, *, suffix: str | None = None) -> int:
    label = f"msg:{seq}" if suffix is None else f"msg:{seq}:{suffix}"
    return seeds.derive(thread_seed, label)
