"""Preenchimento de colunas `llm_*` (DD-01 §C.3.3, §C.3.4, §C.4): modos `unique` e `pool`.

`LLMChunkContext`/`RowContext` são o contrato que a trilha C expõe para a trilha D consumir
(D ainda não existe neste marco; C.4 pede `LLMColumnFiller.fill(chunk_ctx, columns)`, mas o
formato exato de `chunk_ctx` é decisão de integração do step S5). Aqui a unidade de trabalho é
`RowContext` — uma linha com as colunas determinísticas da própria linha (`same_row`) e, por
coluna `ref`, as colunas determinísticas do pai (`parent_rows`) — porque a chamada ao provedor é
inerentemente sequencial (rede), então a trilha C itera linhas em Python (AGENTS.md, "efeitos
colaterais inerentemente sequenciais").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np

from dataipsum import seeds
from dataipsum.contracts.executor import ChunkResultFlags
from dataipsum.contracts.llm import LLMProvider, LLMRequest
from dataipsum.errors import LLMError
from dataipsum.llm import template
from dataipsum.llm.cache import CacheKeyParts, DiskCache, cache_key
from dataipsum.llm.retry import CircuitBreaker, RetryPolicy, call_with_retry
from dataipsum.llm.toxicity import is_offensive

if TYPE_CHECKING:
    from dataipsum.llm.toxicity import CombinedClassifier, DetoxifyClassifier, WordlistClassifier
    from dataipsum.schema.models import ColumnSpec, Schema, TableSpec

    ToxicityClassifierLike = CombinedClassifier | DetoxifyClassifier | WordlistClassifier

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_DEFAULT_TEMPLATE_BY_TYPE = {
    "llm_post": "llm_post.txt",
    "llm_email": "llm_email.txt",
    "llm_contrato": "llm_contrato.txt",
    "conversa": "conversa.txt",
}
_POOL_INSTRUCTION = (
    "Escreva um texto seguindo o modelo abaixo, mas MANTENHA os marcadores entre chaves "
    "(como {coluna} ou {ref.coluna}) exatamente como estão escritos, sem substituí-los ou "
    "traduzi-los. Eles serão preenchidos depois, automaticamente."
)
_MIN_MAX_TOKENS = 16
_DEFAULT_MAX_TOKENS = 2048
_LOREM_SENTENCES = (
    "Texto de exemplo gerado automaticamente enquanto o conteúdo real não fica pronto.",
    "Conteúdo temporário aguardando geração pelo provedor de linguagem.",
    "Este é um espaço reservado determinístico, sem relação com o conteúdo final.",
    "Placeholder gerado pelo dataIpsum: será substituído na próxima execução de resume.",
)

Mode = Literal["unique", "pool"]
ToxicityMode = Literal["allow", "block", "ratio"]
OnFailure = Literal["pending", "placeholder"]


def default_template(column_type: str) -> str:
    filename = _DEFAULT_TEMPLATE_BY_TYPE.get(column_type)
    if filename is None:
        raise LLMError(f"sem template padrão para o tipo '{column_type}'")
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def offensive_prompt_suffix() -> str:
    return (_PROMPTS_DIR / "ofensivo.txt").read_text(encoding="utf-8")


@dataclass(frozen=True)
class ColumnLLMConfig:
    provider: str
    prompt: str | None
    system: str | None
    mode: Mode
    pool_size: int
    toxicity: ToxicityMode
    toxicity_ratio: float | None
    on_failure: OnFailure
    max_regenerations: int
    max_length: int | None


def _optional_str_param(params: Mapping[str, object], key: str) -> str | None:
    value = params.get(key)
    return value if isinstance(value, str) else None


def _int_param(params: Mapping[str, object], key: str, default: int) -> int:
    value = params.get(key, default)
    return int(value) if isinstance(value, int | float | str) else default


def _float_param(params: Mapping[str, object], key: str) -> float | None:
    value = params.get(key)
    return float(value) if isinstance(value, int | float) else None


def _optional_int_param(params: Mapping[str, object], key: str) -> int | None:
    value = params.get(key)
    return int(value) if isinstance(value, int | float | str) else None


def _mode_param(params: Mapping[str, object]) -> Mode:
    value = params.get("mode", "unique")
    return value if value in ("unique", "pool") else "unique"


def _toxicity_param(params: Mapping[str, object]) -> ToxicityMode:
    value = params.get("toxicity", "block")
    return value if value in ("allow", "block", "ratio") else "block"


def _on_failure_param(params: Mapping[str, object]) -> OnFailure:
    value = params.get("on_failure", "pending")
    return value if value in ("pending", "placeholder") else "pending"


def column_llm_config(column: ColumnSpec, *, default_provider: str) -> ColumnLLMConfig:
    params = column.params
    return ColumnLLMConfig(
        provider=str(params.get("provider", default_provider)),
        prompt=_optional_str_param(params, "prompt"),
        system=_optional_str_param(params, "system"),
        mode=_mode_param(params),
        pool_size=_int_param(params, "pool_size", 50),
        toxicity=_toxicity_param(params),
        toxicity_ratio=_float_param(params, "toxicity_ratio"),
        on_failure=_on_failure_param(params),
        max_regenerations=_int_param(params, "max_regenerations", 3),
        max_length=column.max_length,
    )


@dataclass(frozen=True)
class RowContext:
    """Uma linha: `row` é o índice global, `same_row`/`parent_rows` já vêm resolvidos por
    `GenContext.same_row`/`GenContext.parent_rows` (contrato do DD-00) e reindexados por `ref`."""

    row: int
    same_row: Mapping[str, object]
    parent_rows: Mapping[str, Mapping[str, object]]


@dataclass(frozen=True)
class FillOutcome:
    status: Literal["done", "pending_llm"]
    texts: list[str | None]
    is_offensive: list[bool]
    is_placeholder: list[bool]
    flags: ChunkResultFlags = field(default_factory=ChunkResultFlags)


@dataclass
class LLMEngine:
    """Amarra provedor(es), cache, classificador de toxicidade e política de retry/circuito."""

    providers: Mapping[str, LLMProvider]
    toxicity_classifier: ToxicityClassifierLike
    toxicity_threshold: float = 0.5
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    cache: DiskCache | None = None

    def call(self, provider_name: str, req: LLMRequest, *, seed_chunk: int) -> str:
        provider = self.providers[provider_name]
        key = None
        if self.cache is not None:
            key = cache_key(
                CacheKeyParts(
                    kind=provider_name,
                    base_url=getattr(provider, "base_url", None),
                    model=getattr(provider, "model", ""),
                    system=req.system,
                    prompt=req.prompt,
                    json_schema=req.json_schema,
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                    seed=req.seed,
                )
            )
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        response = call_with_retry(
            provider,
            req,
            policy=self.retry_policy,
            seed_chunk=seed_chunk,
            circuit_breaker=self.circuit_breaker,
            provider_name=provider_name,
        )
        if self.cache is not None and key is not None:
            self.cache.put(key, text=response.text, model=getattr(provider, "model", ""))
        return response.text


def max_tokens_for(max_length: int | None) -> int:
    if max_length is None:
        return _DEFAULT_MAX_TOKENS
    return max(_MIN_MAX_TOKENS, max_length // 2 + 64)


def truncate_on_word_boundary(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    return truncated if last_space <= 0 else truncated[:last_space]


def offensive_system(system: str | None) -> str:
    return ((system or "") + "\n\n" + offensive_prompt_suffix()).strip()


def with_length_instruction(prompt: str, max_length: int | None) -> str:
    """`Se N existe, o template recebe a instrução "no máximo N caracteres"` (§C.3.2)."""
    if max_length is None:
        return prompt
    return f"{prompt}\n\nEscreva no máximo {max_length} caracteres."


def _lorem_placeholder(seed_col: int, row: int, max_length: int | None) -> str:
    row_array = np.array([row], dtype=np.int64)
    index = int(seeds.choice(seed_col, row_array, 5, len(_LOREM_SENTENCES))[0])
    text = _LOREM_SENTENCES[index]
    return truncate_on_word_boundary(text, max_length) if max_length is not None else text


def _is_target_offensive_row(seed_col: int, row: int, ratio: float) -> bool:
    row_array = np.array([row], dtype=np.int64)
    value = float(seeds.uniform(seed_col, row_array, 3)[0])
    return value < ratio


def _generate_unique_cell(
    engine: LLMEngine,
    config: ColumnLLMConfig,
    prompt_text: str,
    base_seed: int,
    max_tokens: int,
    *,
    target_offensive: bool,
) -> tuple[str, bool]:
    """Devolve `(texto, is_offensive)`; levanta `LLMError` se as regenerações se esgotarem."""
    needs_clean = config.toxicity == "block" or (
        config.toxicity == "ratio" and not target_offensive
    )
    max_attempts = config.max_regenerations + 1 if needs_clean else 1
    system_text = offensive_system(config.system) if target_offensive else (config.system or "")
    last_text = ""
    last_offensive = True
    for attempt in range(max_attempts):
        seed = base_seed if attempt == 0 else seeds.derive(base_seed, f"regen:{attempt}")
        req = LLMRequest(
            system=system_text,
            prompt=prompt_text,
            max_tokens=max_tokens,
            temperature=0.0,
            seed=seed,
        )
        text = engine.call(config.provider, req, seed_chunk=seed)
        score = engine.toxicity_classifier.score([text])[0]
        offensive = is_offensive(score, engine.toxicity_threshold)
        if not needs_clean or not offensive:
            return text, offensive
        last_text, last_offensive = text, offensive
    raise ToxicityExhaustedError(last_text, last_offensive)


class ToxicityExhaustedError(LLMError):
    def __init__(self, last_text: str, last_offensive: bool) -> None:
        super().__init__("regenerações de toxicidade esgotadas sem produzir texto aceitável")
        self.last_text = last_text
        self.last_offensive = last_offensive


def fill_unique_column(
    engine: LLMEngine,
    schema: Schema,
    table: TableSpec,
    column: ColumnSpec,
    rows: Sequence[RowContext],
    *,
    root_seed: int,
) -> FillOutcome:
    """Modo `unique` (§C.3.3): uma chamada por linha, seed `seed_llm(coluna, linha)`."""
    default_provider = schema.llm.default_provider if schema.llm is not None else ""
    config = column_llm_config(column, default_provider=default_provider)
    if config.mode != "unique":
        raise LLMError(f"fill_unique_column exige mode='unique' (coluna '{column.name}')")

    template_text = config.prompt or default_template(column.type)
    template.TemplateValidator().validate(schema, table, column, template_text)
    tokens = template.parse_template(template_text)
    max_tokens = max_tokens_for(config.max_length)
    seed_col = seeds.seed_column(seeds.seed_table(root_seed, table.name), column.name)

    texts: list[str | None] = []
    offensive_flags: list[bool] = []
    provider_failed = False
    exhausted_count = 0
    for row_ctx in rows:
        row_seed = seeds.seed_llm(seed_col, row_ctx.row)
        target_offensive = (
            config.toxicity == "ratio"
            and config.toxicity_ratio is not None
            and (_is_target_offensive_row(seed_col, row_ctx.row, config.toxicity_ratio))
        )
        prompt_text = with_length_instruction(
            template.render(tokens, same_row=row_ctx.same_row, parent_values=row_ctx.parent_rows),
            config.max_length,
        )
        try:
            text, offensive = _generate_unique_cell(
                engine, config, prompt_text, row_seed, max_tokens, target_offensive=target_offensive
            )
        except ToxicityExhaustedError:
            exhausted_count += 1
            texts.append(None)
            offensive_flags.append(False)
            continue
        except LLMError:
            provider_failed = True
            texts.append(None)
            offensive_flags.append(False)
            continue
        texts.append(
            truncate_on_word_boundary(text, config.max_length)
            if config.max_length is not None
            else text
        )
        offensive_flags.append(offensive)

    if provider_failed:
        return _provider_failure_outcome(config, rows, seed_col)
    if exhausted_count > 0:
        return FillOutcome(
            status="pending_llm",
            texts=texts,
            is_offensive=offensive_flags,
            is_placeholder=[False for _ in rows],
            flags=ChunkResultFlags(toxicity_exhausted=exhausted_count),
        )
    return FillOutcome(
        status="done",
        texts=texts,
        is_offensive=offensive_flags,
        is_placeholder=[False for _ in rows],
    )


def _provider_failure_outcome(
    config: ColumnLLMConfig, rows: Sequence[RowContext], seed_col: int
) -> FillOutcome:
    """§C.3.7: falha do provedor esgota o chunk inteiro. O motor nunca escolhe `placeholder`
    sozinho — só entra aqui se o usuário já pediu `on_failure: placeholder` na coluna."""
    if config.on_failure == "placeholder":
        placeholder_texts: list[str | None] = [
            _lorem_placeholder(seed_col, row_ctx.row, config.max_length) for row_ctx in rows
        ]
        return FillOutcome(
            status="pending_llm",
            texts=placeholder_texts,
            is_offensive=[False for _ in rows],
            is_placeholder=[True for _ in rows],
            flags=ChunkResultFlags(placeholders=len(rows)),
        )
    return FillOutcome(
        status="pending_llm",
        texts=[None for _ in rows],
        is_offensive=[False for _ in rows],
        is_placeholder=[False for _ in rows],
    )


@dataclass(frozen=True)
class Pool:
    texts: tuple[str, ...]
    variables: tuple[template.Var, ...]


class PoolBuilder:
    """`PoolBuilder.build(table, column) -> Pool` (§C.4): gerado antes dos chunks da tabela."""

    def __init__(self, engine: LLMEngine) -> None:
        self._engine = engine

    def build(
        self, schema: Schema, table: TableSpec, column: ColumnSpec, *, root_seed: int
    ) -> Pool:
        default_provider = schema.llm.default_provider if schema.llm is not None else ""
        config = column_llm_config(column, default_provider=default_provider)
        if config.mode != "pool":
            raise LLMError(f"PoolBuilder exige mode='pool' (coluna '{column.name}')")

        template_text = config.prompt or default_template(column.type)
        variables = template.TemplateValidator().validate(schema, table, column, template_text)
        seed_col = seeds.seed_column(seeds.seed_table(root_seed, table.name), column.name)
        offensive_count = (
            round(config.pool_size * config.toxicity_ratio)
            if config.toxicity == "ratio" and config.toxicity_ratio
            else 0
        )
        prompt = with_length_instruction(
            f"{_POOL_INSTRUCTION}\n\n{template_text}", config.max_length
        )
        max_tokens = max_tokens_for(config.max_length)

        texts: list[str] = []
        for index in range(config.pool_size):
            base_seed = seeds.derive(seed_col, f"pool:{index}")
            target_offensive = index < offensive_count
            text = self._build_one(
                config, prompt, variables, base_seed, max_tokens, target_offensive
            )
            if text is not None:
                texts.append(text)
        return Pool(texts=tuple(texts), variables=variables)

    def _build_one(
        self,
        config: ColumnLLMConfig,
        prompt: str,
        variables: tuple[template.Var, ...],
        base_seed: int,
        max_tokens: int,
        target_offensive: bool,
    ) -> str | None:
        system = offensive_system(config.system) if target_offensive else (config.system or "")
        for attempt in range(config.max_regenerations + 1):
            seed = base_seed if attempt == 0 else seeds.derive(base_seed, f"regen:{attempt}")
            req = LLMRequest(
                system=system, prompt=prompt, max_tokens=max_tokens, temperature=0.0, seed=seed
            )
            try:
                text = self._engine.call(config.provider, req, seed_chunk=seed)
            except LLMError:
                return None
            if not template.unknown_markers(text, variables):
                return text
        return None


def fill_pool_column(
    pool: Pool,
    schema: Schema,
    table: TableSpec,
    column: ColumnSpec,
    rows: Sequence[RowContext],
    *,
    root_seed: int,
) -> FillOutcome:
    """Modo `pool` (§C.3.4, "Por linha"): índice `draws.integers(slot 2, 0, K)`, preenchido."""
    if not pool.texts:
        return FillOutcome(
            status="pending_llm",
            texts=[None for _ in rows],
            is_offensive=[False for _ in rows],
            is_placeholder=[False for _ in rows],
        )
    default_provider = schema.llm.default_provider if schema.llm is not None else ""
    config = column_llm_config(column, default_provider=default_provider)
    seed_col = seeds.seed_column(seeds.seed_table(root_seed, table.name), column.name)
    pool_size = len(pool.texts)
    texts: list[str | None] = []
    for row_ctx in rows:
        row_array = np.array([row_ctx.row], dtype=np.int64)
        index = int(seeds.integers(seed_col, row_array, 2, 0, pool_size)[0])
        chosen = pool.texts[index]
        filled = template.fill_pool_text(
            chosen, same_row=row_ctx.same_row, parent_values=row_ctx.parent_rows
        )
        texts.append(
            truncate_on_word_boundary(filled, config.max_length)
            if config.max_length is not None
            else filled
        )
    return FillOutcome(
        status="done",
        texts=texts,
        is_offensive=[False for _ in rows],
        is_placeholder=[False for _ in rows],
    )


class LLMColumnFiller:
    """`LLMColumnFiller.fill(chunk_ctx, columns) -> (arrays, flags)` (§C.4).

    A trilha D ainda não existe neste marco; os métodos abaixo expõem a mesma lógica por coluna
    (`fill_unique`/`fill_pool`), que o construtor de chunk da trilha D chamará depois das colunas
    determinísticas. `fill_unique_column`/`fill_pool_column`/`PoolBuilder` (módulo-level) são o
    contrato estável; esta classe é um envelope fino de conveniência.
    """

    def __init__(self, engine: LLMEngine) -> None:
        self.engine = engine

    def fill_unique(
        self,
        schema: Schema,
        table: TableSpec,
        column: ColumnSpec,
        rows: Sequence[RowContext],
        *,
        root_seed: int,
    ) -> FillOutcome:
        return fill_unique_column(self.engine, schema, table, column, rows, root_seed=root_seed)

    def fill_pool(
        self,
        pool: Pool,
        schema: Schema,
        table: TableSpec,
        column: ColumnSpec,
        rows: Sequence[RowContext],
        *,
        root_seed: int,
    ) -> FillOutcome:
        return fill_pool_column(pool, schema, table, column, rows, root_seed=root_seed)


def combine_offensive_flags(*column_outcomes: FillOutcome) -> list[bool]:
    """`is_offensive` por linha é o OR entre as colunas LLM da linha (§C.3.5)."""
    if not column_outcomes:
        return []
    length = len(column_outcomes[0].is_offensive)
    return [any(outcome.is_offensive[i] for outcome in column_outcomes) for i in range(length)]
