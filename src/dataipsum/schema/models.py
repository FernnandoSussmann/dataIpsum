"""Modelo Pydantic do schema YAML do dataIpsum (DD-00 §3.3).

A validação é feita em camadas (§3.3 "Validação em camadas"). Este módulo cobre a
camada 2 (estrutura, via Pydantic) e expõe `validate_with_registry`/`normalize_schema`
para as camadas 3 e 4, que dependem do registry (nomes de tipo, `Generator.validate_params`,
`Generator.implied_columns`, `Planner.implied_columns`, `Planner.validate`). Como as
trilhas A, B e C ainda não existem neste marco, essas duas funções recebem um
`ValidationContext` opcional: sem ele, a camada 4 simplesmente não roda (nenhum erro é
inventado aqui), e as trilhas futuras plugam suas implementações reais sem mudar este
módulo.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from dataipsum.errors import SchemaError, ValidationError

if TYPE_CHECKING:
    from dataipsum.contracts.generator import Generator
    from dataipsum.contracts.planner import Planner

IDENTIFIER_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

MAX_TABLES = 200
MAX_COLUMNS_PER_TABLE = 500

PrimaryKeyStrategy = Literal["sequence", "seeded_int", "seeded_uuid", "composite"]
Relation = Literal["one_to_one", "one_to_many", "many_to_many", "thread"]
Format = Literal["masked", "unmasked"]


def _check_identifier(value: str) -> str:
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(
            f"identificador inválido: '{value}' deve casar com '{IDENTIFIER_PATTERN.pattern}'"
        )
    return value


Identifier = Annotated[str, AfterValidator(_check_identifier)]


class ZipfDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    s: float = Field(gt=0)


class Distribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zipf: ZipfDistribution | None = None


class CardinalityRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int = Field(ge=0)
    max: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_min_le_max(self) -> CardinalityRange:
        if self.min > self.max:
            raise ValueError("'min' não pode ser maior que 'max'")
        return self


class CardinalitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    range: CardinalityRange | None = None
    distribution: Distribution | None = None


class RowsFromSpec(BaseModel):
    """Semântica plena na trilha B (DD-01); aqui só a forma estrutural do campo."""

    model_config = ConfigDict(extra="forbid")

    via: Identifier
    relation: Relation
    cardinality: CardinalitySpec | None = None
    coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    pair: str | None = None


class PrimaryKeySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[Identifier] = Field(min_length=1)
    strategy: PrimaryKeyStrategy
    start: int | None = None
    step: int | None = None


class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Identifier
    type: str = Field(min_length=1)
    params: dict[str, object] = Field(default_factory=dict)
    null_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    invalid_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    format: Format | None = None
    max_length: int | None = Field(default=None, ge=1)
    locale: str | None = None

    @property
    def is_llm(self) -> bool:
        return self.type.startswith("llm_")


class TableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Identifier
    rows: int | None = Field(default=None, ge=0)
    rows_from: RowsFromSpec | None = None
    thread: dict[str, object] | None = None
    primary_key: PrimaryKeySpec
    locale: str | None = None
    columns: list[ColumnSpec] = Field(min_length=1, max_length=MAX_COLUMNS_PER_TABLE)

    @model_validator(mode="after")
    def _check_rows_xor_rows_from(self) -> TableSpec:
        if self.rows is None and self.rows_from is None:
            raise ValueError(
                "tabela precisa definir 'rows' (tabela raiz) ou 'rows_from' (tabela filha)"
            )
        if self.rows is not None and self.rows_from is not None:
            raise ValueError("'rows' e 'rows_from' são mutuamente exclusivos")
        return self

    @model_validator(mode="after")
    def _check_thread_requires_relation(self) -> TableSpec:
        is_thread_relation = self.rows_from is not None and self.rows_from.relation == "thread"
        if self.thread is not None and not is_thread_relation:
            raise ValueError("'thread' só é permitido quando 'rows_from.relation' é 'thread'")
        return self

    @model_validator(mode="after")
    def _check_composite_requires_many_to_many(self) -> TableSpec:
        is_many_to_many = self.rows_from is not None and self.rows_from.relation == "many_to_many"
        if self.primary_key.strategy == "composite" and not is_many_to_many:
            raise ValueError(
                "estratégia de chave primária 'composite' só é válida com "
                "'rows_from.relation' igual a 'many_to_many'"
            )
        return self

    @model_validator(mode="after")
    def _check_unique_column_names(self) -> TableSpec:
        names = [column.name for column in self.columns]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"nomes de coluna duplicados: {duplicates}")
        return self


class RetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=5, ge=1)
    base_delay_s: float = Field(default=1.0, gt=0.0)
    max_delay_s: float = Field(default=60.0, gt=0.0)


class LLMProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["ollama", "openai_compatible", "anthropic"]
    model: str = Field(min_length=1)
    base_url: str | None = None
    api_key_env: str | None = None
    max_concurrency: int = Field(default=1, ge=1)
    timeout_s: float = Field(default=120.0, gt=0.0)
    temperature: float = Field(default=0.0, ge=0.0)


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_provider: str
    providers: dict[str, LLMProviderConfig] = Field(min_length=1)
    retry: RetryConfig = Field(default_factory=RetryConfig)

    @model_validator(mode="after")
    def _check_default_provider_exists(self) -> LLMConfig:
        if self.default_provider not in self.providers:
            raise ValueError(
                f"'default_provider' ('{self.default_provider}') não está em 'providers'"
            )
        return self


class LimitsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_rows_total: int = Field(default=100_000_000, ge=1)


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    name: Identifier = "dataipsum"
    seed: int | None = Field(default=None, ge=0, lt=2**63)
    locale: str = "pt_BR"
    chunk_size: int = Field(default=10_000, ge=100, le=1_000_000)
    limits: LimitsSpec = Field(default_factory=LimitsSpec)
    llm: LLMConfig | None = None
    tables: list[TableSpec] = Field(min_length=1, max_length=MAX_TABLES)

    @model_validator(mode="after")
    def _check_unique_table_names(self) -> Schema:
        names = [table.name for table in self.tables]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"nomes de tabela duplicados: {duplicates}")
        return self

    @model_validator(mode="after")
    def _check_llm_section_present_for_llm_columns(self) -> Schema:
        has_llm_column = any(column.is_llm for table in self.tables for column in table.columns)
        if has_llm_column and self.llm is None:
            raise ValueError("schema tem coluna 'llm_*', mas não define a seção 'llm'")
        return self


def effective_locale(schema: Schema, table: TableSpec, column: ColumnSpec) -> str:
    """Locale efetivo de uma coluna: coluna > tabela > schema (DD-00 §3.3)."""
    return column.locale or table.locale or schema.locale


@dataclass(frozen=True)
class ValidationContext:
    """Hook para a validação delegada ao registry (camada 4, DD-00 §3.3).

    Sem generators/planner (o caso do S2, antes das trilhas A/B/C existirem), as
    funções que recebem este contexto simplesmente não geram erros de camada 4:
    a estrutura (camada 2, Pydantic) já foi verificada antes.
    """

    generators: Mapping[str, Generator] = field(default_factory=dict)
    planner: Planner | None = None


def _column_index(table: TableSpec, name: str) -> int:
    return next(index for index, column in enumerate(table.columns) if column.name == name)


def _validate_capabilities(
    table: TableSpec, table_index: int, ctx: ValidationContext
) -> list[ValidationError]:
    return [
        error
        for column_index, column in enumerate(table.columns)
        for error in _validate_column_capabilities(column, table_index, column_index, ctx)
    ]


def _validate_column_capabilities(
    column: ColumnSpec, table_index: int, column_index: int, ctx: ValidationContext
) -> list[ValidationError]:
    prefix = f"tables[{table_index}].columns[{column_index}]"
    generator = ctx.generators.get(column.type)
    if generator is None:
        return [
            ValidationError(
                path=f"{prefix}.type", message=f"tipo de coluna desconhecido: '{column.type}'"
            )
        ]
    errors = []
    if column.invalid_ratio > 0 and not generator.supports_invalid:
        errors.append(
            ValidationError(
                path=f"{prefix}.invalid_ratio",
                message=f"'invalid_ratio' não é aceito pelo tipo '{column.type}'",
            )
        )
    if column.format is not None and not generator.supports_format:
        errors.append(
            ValidationError(
                path=f"{prefix}.format",
                message=f"'format' não é aceito pelo tipo '{column.type}'",
            )
        )
    errors.extend(
        ValidationError(
            path=f"{prefix}.params.{sub.path}" if sub.path else f"{prefix}.params",
            message=sub.message,
        )
        for sub in generator.validate_params(column, ctx)
    )
    return errors


def _dependency_graph(table: TableSpec, ctx: ValidationContext) -> dict[str, list[str]]:
    return {
        column.name: ctx.generators[column.type].depends_on(column)
        for column in table.columns
        if column.type in ctx.generators
    }


def _has_cycle(graph: Mapping[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited or node not in graph:
            return False
        visiting.add(node)
        found = any(visit(dep) for dep in graph[node])
        visiting.discard(node)
        visited.add(node)
        return found

    return any(visit(node) for node in graph)


def _validate_depends_on(
    table: TableSpec, table_index: int, ctx: ValidationContext
) -> list[ValidationError]:
    graph = _dependency_graph(table, ctx)
    column_by_name = {column.name: column for column in table.columns}
    missing = [
        ValidationError(
            path=f"tables[{table_index}].columns[{_column_index(table, name)}]",
            message=f"depende de coluna inexistente '{dep}'",
        )
        for name, deps in graph.items()
        for dep in deps
        if dep not in column_by_name
    ]
    non_deterministic = [
        ValidationError(
            path=f"tables[{table_index}].columns[{_column_index(table, name)}]",
            message=f"não pode depender da coluna não determinística '{dep}' (tipo 'llm_*')",
        )
        for name, deps in graph.items()
        for dep in deps
        if dep in column_by_name and column_by_name[dep].is_llm
    ]
    cycle = (
        [
            ValidationError(
                path=f"tables[{table_index}]",
                message="ciclo de dependências entre colunas ('depends_on')",
            )
        ]
        if _has_cycle(graph)
        else []
    )
    return missing + non_deterministic + cycle


def validate_with_registry(
    schema: Schema, ctx: ValidationContext | None = None
) -> list[ValidationError]:
    """Camadas 3 (nomes/tipos) e 4 (delegada ao registry) de "Validação em camadas".

    Sem `ctx` (nenhum registry disponível), retorna lista vazia: a camada 4 depende
    de `Generator`/`Planner` reais, que só existem a partir das trilhas A, B e C.
    """
    if ctx is None:
        return []
    table_errors = [
        error
        for table_index, table in enumerate(schema.tables)
        for error in (
            _validate_capabilities(table, table_index, ctx)
            + _validate_depends_on(table, table_index, ctx)
        )
    ]
    planner_errors = ctx.planner.validate(schema) if ctx.planner is not None else []
    return table_errors + list(planner_errors)


def _implied_columns_for_table(table: TableSpec, ctx: ValidationContext) -> list[ColumnSpec]:
    generator_implied = [
        implied
        for column in table.columns
        if column.type in ctx.generators
        for implied in ctx.generators[column.type].implied_columns(column)
    ]
    planner_implied = list(ctx.planner.implied_columns(table)) if ctx.planner is not None else []
    combined = generator_implied + planner_implied
    seen: dict[str, ColumnSpec] = {}
    for column in combined:
        seen.setdefault(column.name, column)
    return list(seen.values())


def normalize_schema(schema: Schema, ctx: ValidationContext | None = None) -> Schema:
    """Acrescenta `implied_columns` (Generator e Planner) ao fim de cada tabela.

    Rejeita colisão com colunas declaradas pelo usuário (DD-00 §3.5). Sem `ctx`,
    devolve o schema inalterado: não há generators/planner para consultar.
    """
    if ctx is None:
        return schema
    errors: list[ValidationError] = []
    normalized_tables: list[TableSpec] = []
    for table_index, table in enumerate(schema.tables):
        implied = _implied_columns_for_table(table, ctx)
        existing_names = {column.name for column in table.columns}
        collisions = sorted(existing_names & {column.name for column in implied})
        if collisions:
            errors.append(
                ValidationError(
                    path=f"tables[{table_index}].columns",
                    message=(
                        f"coluna(s) implícita(s) colidem com coluna(s) declarada(s): {collisions}"
                    ),
                )
            )
            continue
        normalized_tables.append(table.model_copy(update={"columns": [*table.columns, *implied]}))
    if errors:
        raise SchemaError(errors)
    return schema.model_copy(update={"tables": normalized_tables})
