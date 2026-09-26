"""Testes dos campos com regra de documentos (DD-01 A.6): cpf, rg, cartao_credito."""

from __future__ import annotations

import re

import pytest

from dataipsum.types import card_brand, is_valid_cpf, is_valid_rg_sp, luhn_is_valid

# --- CPF ---------------------------------------------------------------


def test_cpf_golden_valido() -> None:
    assert is_valid_cpf("529.982.247-25")


@pytest.mark.slow
def test_cpf_100k_validos_por_padrao(registry, column_factory, generate_column) -> None:
    column = column_factory("cpf")
    values = generate_column(registry, column, row_count=100_000).to_pylist()
    assert all(is_valid_cpf(v) for v in values)


@pytest.mark.slow
def test_cpf_invalid_ratio_1_todos_falham(registry, column_factory, generate_column) -> None:
    column = column_factory("cpf", invalid_ratio=1.0)
    values = generate_column(registry, column, row_count=100_000, invalid_ratio=1.0).to_pylist()
    assert all(not is_valid_cpf(v) for v in values)


def test_cpf_nenhuma_base_repetida(registry, column_factory, generate_column) -> None:
    column = column_factory("cpf")
    values = generate_column(registry, column, row_count=20_000).to_pylist()
    bases = {re.sub(r"\D", "", v)[:9] for v in values}
    assert all(len(set(base)) > 1 for base in bases)


def test_cpf_masked_formato_exato(registry, column_factory, generate_column) -> None:
    column = column_factory("cpf", format="masked")
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(re.fullmatch(r"\d{3}\.\d{3}\.\d{3}-\d{2}", v) for v in values)


def test_cpf_unmasked_formato_exato(registry, column_factory, generate_column) -> None:
    column = column_factory("cpf", format="unmasked")
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(re.fullmatch(r"\d{11}", v) for v in values)


def test_cpf_invalid_ratio_proporcao_aproximada(registry, column_factory, generate_column) -> None:
    column = column_factory("cpf", invalid_ratio=0.2, format="unmasked")
    values = generate_column(registry, column, row_count=100_000, invalid_ratio=0.2).to_pylist()
    invalid_count = sum(1 for v in values if not is_valid_cpf(v))
    ratio = invalid_count / len(values)
    assert 0.19 <= ratio <= 0.21


# --- RG ------------------------------------------------------------------


def test_rg_golden_base_12345678_gera_dv_2(registry, column_factory) -> None:
    assert is_valid_rg_sp("12.345.678-2")
    assert is_valid_rg_sp("123456782")


@pytest.mark.slow
def test_rg_100k_validos_por_padrao(registry, column_factory, generate_column) -> None:
    column = column_factory("rg")
    values = generate_column(registry, column, row_count=100_000).to_pylist()
    assert all(is_valid_rg_sp(v) for v in values)


def test_rg_caso_dv_x_existe_e_e_valido(registry, column_factory, generate_column) -> None:
    column = column_factory("rg", format="unmasked")
    values = generate_column(registry, column, row_count=20_000).to_pylist()
    assert any(v.endswith("X") for v in values)
    assert all(is_valid_rg_sp(v) for v in values if v.endswith("X"))


def test_rg_invalidos_falham(registry, column_factory, generate_column) -> None:
    column = column_factory("rg", invalid_ratio=1.0)
    values = generate_column(registry, column, row_count=20_000, invalid_ratio=1.0).to_pylist()
    assert all(not is_valid_rg_sp(v) for v in values)


def test_rg_masked_formato_exato(registry, column_factory, generate_column) -> None:
    column = column_factory("rg", format="masked")
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(re.fullmatch(r"\d{2}\.\d{3}\.\d{3}-[\dX]", v) for v in values)


def test_rg_unmasked_formato_exato(registry, column_factory, generate_column) -> None:
    column = column_factory("rg", format="unmasked")
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(re.fullmatch(r"\d{8}[\dX]", v) for v in values)


# --- Cartão de crédito ------------------------------------------------------


@pytest.mark.slow
def test_cartao_luhn_valido_em_100k(registry, column_factory, generate_column) -> None:
    column = column_factory("cartao_credito", format="unmasked")
    values = generate_column(registry, column, row_count=100_000).to_pylist()
    assert all(luhn_is_valid(v) for v in values)


def test_cartao_prefixo_e_comprimento_conforme_a_bandeira(
    registry, column_factory, generate_column
) -> None:
    column = column_factory(
        "cartao_credito", params={"brands": ["visa", "amex"]}, format="unmasked"
    )
    values = generate_column(registry, column, row_count=2000).to_pylist()
    for value in values:
        if value.startswith(("34", "37")):
            assert len(value) == 15
        elif value.startswith("4"):
            assert len(value) == 16
        else:
            pytest.fail(f"prefixo inesperado: {value}")


def test_cartao_brands_restringe_bandeiras(registry, column_factory, generate_column) -> None:
    column = column_factory("cartao_credito", params={"brands": ["visa"]}, format="unmasked")
    values = generate_column(registry, column, row_count=1000).to_pylist()
    assert all(card_brand(v) == "visa" for v in values)


def test_cartao_weights_favorece_bandeira(registry, column_factory, generate_column) -> None:
    column = column_factory(
        "cartao_credito",
        params={"brands": ["visa", "amex"], "weights": [0.95, 0.05]},
        format="unmasked",
    )
    values = generate_column(registry, column, row_count=5000).to_pylist()
    visa_count = sum(1 for v in values if v.startswith("4"))
    assert visa_count / len(values) > 0.85


def test_cartao_extra_bins(registry, column_factory, generate_column) -> None:
    column = column_factory(
        "cartao_credito",
        params={
            "brands": ["minha_bandeira"],
            "extra_bins": [{"brand": "minha_bandeira", "prefix": "999", "length": 16}],
        },
        format="unmasked",
    )
    values = generate_column(registry, column, row_count=500).to_pylist()
    assert all(v.startswith("999") and len(v) == 16 for v in values)
    assert all(luhn_is_valid(v) for v in values)


def test_cartao_invalidos_falham_no_luhn(registry, column_factory, generate_column) -> None:
    column = column_factory("cartao_credito", invalid_ratio=1.0, format="unmasked")
    values = generate_column(registry, column, row_count=5000, invalid_ratio=1.0).to_pylist()
    assert all(not luhn_is_valid(v) for v in values)


def test_cartao_mascara_amex_4_6_5(registry, column_factory, generate_column) -> None:
    column = column_factory("cartao_credito", params={"brands": ["amex"]}, format="masked")
    values = generate_column(registry, column, row_count=200).to_pylist()
    assert all(re.fullmatch(r"\d{4} \d{6} \d{5}", v) for v in values)


def test_cartao_mascara_visa_4_4_4_4(registry, column_factory, generate_column) -> None:
    column = column_factory("cartao_credito", params={"brands": ["visa"]}, format="masked")
    values = generate_column(registry, column, row_count=200).to_pylist()
    assert all(re.fullmatch(r"\d{4} \d{4} \d{4} \d{4}", v) for v in values)


# --- locale ------------------------------------------------------------


def test_cpf_em_locale_diferente_de_pt_br_e_erro(registry, column_factory) -> None:
    generator = registry.get_generator("cpf")()
    column = column_factory("cpf", locale="en_US")
    errors = generator.validate_params(column, None)
    assert any(error.path == "locale" for error in errors)


def test_rg_em_locale_diferente_de_pt_br_e_erro(registry, column_factory) -> None:
    generator = registry.get_generator("rg")()
    column = column_factory("rg", locale="en_US")
    errors = generator.validate_params(column, None)
    assert any(error.path == "locale" for error in errors)
