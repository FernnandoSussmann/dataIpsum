"""Fixtures compartilhadas da trilha C (DD-01)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from dataipsum.schema.models import (
    ColumnSpec,
    LLMConfig,
    LLMProviderConfig,
    PrimaryKeySpec,
    RowsFromSpec,
    Schema,
    TableSpec,
)

LLM_CONFIG = LLMConfig(
    default_provider="local",
    providers={"local": LLMProviderConfig(kind="ollama", model="llama3.1:8b")},
)


def build_parent_child_schema(
    *, child_column_type: str = "llm_post", child_max_length: int | None = 280
) -> tuple[Schema, TableSpec, TableSpec]:
    """`usuarios` (pai) <- `posts` (filho, `autor_id` referencia `usuarios`)."""
    usuarios = TableSpec(
        name="usuarios",
        rows=10,
        primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
        columns=[
            ColumnSpec(name="id", type="int"),
            ColumnSpec(name="nome", type="nome_proprio"),
        ],
    )
    posts = TableSpec(
        name="posts",
        primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
        rows_from=RowsFromSpec(via="autor_id", relation="one_to_many"),
        columns=[
            ColumnSpec(name="id", type="int"),
            ColumnSpec(name="autor_id", type="ref", params={"table": "usuarios"}),
            ColumnSpec(
                name="conteudo",
                type=child_column_type,
                max_length=child_max_length,
                params={"provider": "local"},
            ),
        ],
    )
    schema = Schema(version=1, tables=[usuarios, posts], llm=LLM_CONFIG)
    return schema, usuarios, posts


@pytest.fixture
def parent_child_schema() -> Callable[..., tuple[Schema, TableSpec, TableSpec]]:
    """Fábrica: `parent_child_schema(child_column_type=..., child_max_length=...)`."""
    return build_parent_child_schema
