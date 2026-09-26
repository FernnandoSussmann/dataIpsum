"""Testes de `nome_proprio` e `email` (DD-01 A.6)."""

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest

from dataipsum.contracts.generator import RowBatch
from dataipsum.seeds import Draws, seed_column, seed_table
from dataipsum.types import is_valid_email

# --- nome_proprio ------------------------------------------------------


def _starts_with_some_first_name(value: str, first_names: set[str]) -> bool:
    """`nome_proprio` (`full`) começa por um nome de `first_names`, que pode ele
    mesmo conter espaço (ex.: 'Anna Liz' no snapshot do Faker pt_BR)."""
    return any(value == name or value.startswith(name + " ") for name in first_names)


def test_nome_proprio_gender_f(registry, column_factory, generate_column) -> None:
    locale = registry.locales["pt_BR"]
    column = column_factory("nome_proprio", params={"gender": "f"})
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(_starts_with_some_first_name(v, set(locale.first_names_f)) for v in values)


def test_nome_proprio_gender_m(registry, column_factory, generate_column) -> None:
    locale = registry.locales["pt_BR"]
    column = column_factory("nome_proprio", params={"gender": "m"})
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(_starts_with_some_first_name(v, set(locale.first_names_m)) for v in values)


def test_nome_proprio_parts_first_sem_sobrenome(registry, column_factory, generate_column) -> None:
    locale = registry.locales["pt_BR"]
    all_first_names = set(locale.first_names_f) | set(locale.first_names_m)
    column = column_factory("nome_proprio", params={"parts": "first"})
    values = generate_column(registry, column, row_count=200).to_pylist()
    assert all(v in all_first_names for v in values)


def test_nome_proprio_respeita_max_length(registry, column_factory, generate_column) -> None:
    column = column_factory("nome_proprio", max_length=10)
    values = generate_column(registry, column, row_count=5000).to_pylist()
    assert all(len(v) <= 10 for v in values)


def test_nome_proprio_invalid_ratio_e_erro(registry, column_factory) -> None:
    generator = registry.get_generator("nome_proprio")()
    assert generator.supports_invalid is False


# --- email --------------------------------------------------------------


@pytest.mark.slow
def test_email_100k_validos_por_padrao(registry, column_factory, generate_column) -> None:
    column = column_factory("email")
    values = generate_column(registry, column, row_count=100_000).to_pylist()
    assert all(is_valid_email(v) for v in values)


def test_email_invalid_ratio_1_todos_falham_com_cada_variante(
    registry, column_factory, generate_column
) -> None:
    column = column_factory("email", invalid_ratio=1.0)
    values = generate_column(registry, column, row_count=20_000, invalid_ratio=1.0).to_pylist()
    assert all(not is_valid_email(v) for v in values)

    no_at = any("@" not in v for v in values)
    two_at = any(v.count("@") == 2 for v in values)
    double_dot = any(".." in v.split("@")[0] for v in values if "@" in v)
    starts_with_dot = any(v.split("@")[0].startswith(".") for v in values if "@" in v)
    no_tld = any("@" in v and "." not in v.split("@")[1] for v in values)
    has_space = any(" " in v for v in values)
    assert all([no_at, two_at, double_dot, starts_with_dot, no_tld, has_space])


def test_email_dominio_padrao_e_reservado(registry, column_factory, generate_column) -> None:
    column = column_factory("email")
    values = generate_column(registry, column, row_count=2000).to_pylist()
    domains = {v.split("@")[1] for v in values}
    assert domains <= {"example.com", "example.net", "example.org"}


def test_email_domains_customizado_e_usado(registry, column_factory, generate_column) -> None:
    column = column_factory("email", params={"domains": ["meudominio.example"]})
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(v.endswith("@meudominio.example") for v in values)


def test_email_dominio_nao_reservado_emite_aviso(registry, column_factory, caplog) -> None:
    generator = registry.get_generator("email")()
    column = column_factory("email", params={"domains": ["minhaempresa.com"]})
    with caplog.at_level("WARNING", logger="dataipsum.types.person"):
        errors = generator.validate_params(column, None)
    assert errors == []
    assert any("minhaempresa.com" in record.getMessage() for record in caplog.records)


def test_email_dominio_sintaticamente_invalido_e_schema_error(registry, column_factory) -> None:
    generator = registry.get_generator("email")()
    column = column_factory("email", params={"domains": ["nao_e_dominio"]})
    errors = generator.validate_params(column, None)
    assert any(error.path == "domains" for error in errors)


def test_email_name_column_deriva_parte_local(registry, column_factory) -> None:
    generator = registry.get_generator("email")()
    column = column_factory("email", params={"name_column": "nome"})

    class Ctx:
        locale = "pt_BR"

        def same_row(self, names: list[str]) -> dict[str, pa.Array]:
            return {"nome": pa.array(["João da Silva", "Maria Aparecida", None])}

        def parent_rows(self, table, parent_indices, columns):
            raise NotImplementedError

    rows = np.arange(3, dtype=np.int64)
    seed_col = seed_column(seed_table(1, "t"), "email")
    draws = Draws(seed_col=seed_col, rows=rows)
    batch = RowBatch(rows=rows, invalid_mask=np.zeros(3, dtype=bool))
    values = generator.generate(column, batch, draws, Ctx()).to_pylist()

    assert values[0].split("@")[0] in {"joao.silva", "joao_silva", "joaosilva"}
    assert values[1].split("@")[0] in {"maria.aparecida", "maria_aparecida", "mariaaparecida"}
    assert is_valid_email(values[2])


def test_email_name_column_inexistente_e_schema_error(registry, column_factory) -> None:
    from dataipsum.schema.models import Schema, ValidationContext, validate_with_registry

    generators = {name: registry.get_generator(name)() for name in registry.generators}
    schema = Schema(
        version=1,
        tables=[
            {
                "name": "t",
                "rows": 10,
                "primary_key": {"columns": ["id"], "strategy": "sequence"},
                "columns": [
                    {"name": "id", "type": "int"},
                    {"name": "e", "type": "email", "params": {"name_column": "nome_inexistente"}},
                ],
            }
        ],
    )
    errors = validate_with_registry(schema, ValidationContext(generators=generators))
    assert any("nome_inexistente" in error.message for error in errors)


@pytest.mark.slow
def test_email_unique_gera_1m_enderecos_distintos(registry, column_factory) -> None:
    generator = registry.get_generator("email")()
    column = column_factory("email", params={"unique": True})
    rows = np.arange(1_000_000, dtype=np.int64)
    seed_col = seed_column(seed_table(1, "t"), "email")
    draws = Draws(seed_col=seed_col, rows=rows)
    batch = RowBatch(rows=rows, invalid_mask=np.zeros(rows.shape[0], dtype=bool))

    class Ctx:
        locale = "pt_BR"

        def same_row(self, names):
            return {}

        def parent_rows(self, table, parent_indices, columns):
            raise NotImplementedError

    values = generator.generate(column, batch, draws, Ctx()).to_pylist()
    assert len(set(values)) == len(values)
    assert all(is_valid_email(v) for v in values)


def test_email_parte_local_ate_64_e_total_ate_max_length(
    registry, column_factory, generate_column
) -> None:
    column = column_factory("email", params={"unique": True}, max_length=254)
    values = generate_column(registry, column, row_count=5000).to_pylist()
    for value in values:
        local, domain = value.split("@")
        assert len(local) <= 64
        assert len(value) <= 254


def test_email_max_length_acima_do_teto_e_erro(registry, column_factory) -> None:
    generator = registry.get_generator("email")()
    column = column_factory("email", max_length=255)
    errors = generator.validate_params(column, None)
    assert any(error.path == "max_length" for error in errors)
