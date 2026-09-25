"""Fixtures compartilhadas dos testes unitários da trilha F (import/export de schema)."""

from __future__ import annotations

from typing import Any

import pytest

from dataipsum.schema.models import Schema


def build_schema(document: dict[str, Any]) -> Schema:
    """Atalho para `Schema.model_validate` nos testes (a trilha F não tem `SchemaBuilder`)."""
    return Schema.model_validate(document)


@pytest.fixture
def loja_schema() -> Schema:
    """Schema de referência com PK simples, FK 1:N e tipos variados (DD-00 §3.3)."""
    return build_schema(
        {
            "version": 1,
            "name": "loja",
            "tables": [
                {
                    "name": "usuarios",
                    "rows": 1000,
                    "primary_key": {"columns": ["id"], "strategy": "sequence", "start": 1},
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "nome", "type": "nome_proprio", "max_length": 120},
                        {"name": "cpf", "type": "cpf", "format": "masked", "invalid_ratio": 0.02},
                        {"name": "bio", "type": "string", "max_length": 200, "null_ratio": 0.1},
                        {"name": "criado_em", "type": "timestamp"},
                    ],
                },
                {
                    "name": "produtos",
                    "rows": 200,
                    "primary_key": {"columns": ["id"], "strategy": "seeded_uuid"},
                    "columns": [
                        {"name": "id", "type": "uuid"},
                        {"name": "titulo", "type": "string", "max_length": 80},
                        {
                            "name": "preco",
                            "type": "decimal",
                            "params": {"precision": 10, "scale": 2},
                        },
                    ],
                },
                {
                    "name": "pedidos",
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "rows_from": {
                        "via": "usuario_id",
                        "relation": "one_to_many",
                        "cardinality": {"range": {"min": 0, "max": 5}},
                    },
                    "columns": [
                        {"name": "id", "type": "int"},
                        {"name": "usuario_id", "type": "ref", "params": {"table": "usuarios"}},
                        {"name": "produto_id", "type": "ref", "params": {"table": "produtos"}},
                    ],
                },
            ],
        }
    )
