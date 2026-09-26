"""Geradores de documentos (DD-01 A.3): `cpf`, `rg` (padrão SP) e `cartao_credito`,
com as funções de validação públicas correspondentes (DD-01 A.4)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

import dataipsum.contracts.types as logical
from dataipsum.errors import ValidationError
from dataipsum.types import bins as bins_module
from dataipsum.types.drawing import (
    digits_of,
    draw_matrix,
    format_layout,
    index_matrix_to_chars,
    join_columns,
    weighted_choice,
)
from dataipsum.types.luhn import luhn_check_digit
from dataipsum.types.params import check_int, get_param, unknown_params

if TYPE_CHECKING:
    from dataipsum.contracts.generator import GenContext, RowBatch
    from dataipsum.schema.models import ColumnSpec
    from dataipsum.seeds import Draws

_DIGITS = "0123456789"
_SUPPORTED_LOCALES = frozenset({"pt_BR"})


def _no_extra_deps(column: ColumnSpec) -> list[str]:
    return []


def _no_implied_columns(column: ColumnSpec) -> list[ColumnSpec]:
    return []


def _check_locale(column: ColumnSpec) -> list[ValidationError]:
    if column.locale is not None and column.locale not in _SUPPORTED_LOCALES:
        supported = ", ".join(sorted(_SUPPORTED_LOCALES))
        return [
            ValidationError(
                path="locale", message=f"'{column.type}' só suporta os locales: {supported}"
            )
        ]
    return []


def _mod11_digit(weighted_sum: NDArray[np.int64]) -> NDArray[np.int64]:
    remainder = weighted_sum % 11
    return np.where(remainder < 2, 0, 11 - remainder)


# --- CPF ---------------------------------------------------------------

_CPF_DV1_WEIGHTS = np.arange(10, 1, -1, dtype=np.int64)
_CPF_DV2_WEIGHTS = np.arange(11, 1, -1, dtype=np.int64)


@dataclass(frozen=True)
class CpfGenerator:
    name: str = "cpf"
    supports_invalid: bool = True
    supports_format: bool = True
    deterministic: bool = True
    draw_slots: int = 2

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        return unknown_params(column.params, set()) + _check_locale(column)

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        length = 14 if (column.format or "masked") == "masked" else 11
        return logical.char(length, nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        rows = batch.rows
        digits = draw_matrix(draws, 2, 9, 0, 10)
        repeated_base = np.all(digits == digits[:, [0]], axis=1)
        digits[repeated_base, -1] = (digits[repeated_base, -1] + 1) % 10

        dv1 = _mod11_digit((digits * _CPF_DV1_WEIGHTS[None, :]).sum(axis=1))
        with_dv1 = np.concatenate([digits, dv1[:, None]], axis=1)
        dv2 = _mod11_digit((with_dv1 * _CPF_DV2_WEIGHTS[None, :]).sum(axis=1))

        invalid_mask = _invalid_mask(batch, rows.shape[0])
        offset = draws.integers(11, 1, 10)
        dv2 = np.where(invalid_mask, (dv2 + offset) % 10, dv2)

        full = np.concatenate([digits, dv1[:, None], dv2[:, None]], axis=1)
        char_matrix = index_matrix_to_chars(full, _DIGITS)
        layout = _cpf_layout(column.format or "masked")
        return pa.array(format_layout(char_matrix, layout), type=pa.string())


def _cpf_layout(fmt: str) -> list[int | str]:
    if fmt == "unmasked":
        return list(range(11))
    return [0, 1, 2, ".", 3, 4, 5, ".", 6, 7, 8, "-", 9, 10]


def _invalid_mask(batch: RowBatch, row_count: int) -> NDArray[np.bool_]:
    if batch.invalid_mask is None:
        return np.zeros(row_count, dtype=np.bool_)
    return batch.invalid_mask


def _only_digits_and_x(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value).upper()


def is_valid_cpf(value: str) -> bool:
    """`True` se `value` (com ou sem máscara) é um CPF matematicamente válido, sem
    base de dígitos todos iguais (DD-01 A.3)."""
    digits_text = re.sub(r"\D", "", value)
    if len(digits_text) != 11 or len(set(digits_text)) == 1:
        return False
    digits = [int(char) for char in digits_text]
    dv1 = _scalar_mod11(
        sum(digit * weight for digit, weight in zip(digits[:9], range(10, 1, -1), strict=True))
    )
    dv2 = _scalar_mod11(
        sum(
            digit * weight
            for digit, weight in zip(digits[:9] + [dv1], range(11, 1, -1), strict=True)
        )
    )
    return digits[9] == dv1 and digits[10] == dv2


def _scalar_mod11(weighted_sum: int) -> int:
    remainder = weighted_sum % 11
    return 0 if remainder < 2 else 11 - remainder


# --- RG (padrão SP) ------------------------------------------------------

_RG_WEIGHTS = np.arange(2, 10, dtype=np.int64)
_RG_CHARS = _DIGITS + "X"


@dataclass(frozen=True)
class RgGenerator:
    name: str = "rg"
    supports_invalid: bool = True
    supports_format: bool = True
    deterministic: bool = True
    draw_slots: int = 2

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        return unknown_params(column.params, set()) + _check_locale(column)

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        length = 12 if (column.format or "masked") == "masked" else 9
        return logical.char(length, nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        rows = batch.rows
        digits = draw_matrix(draws, 2, 8, 0, 10)
        soma = (digits * _RG_WEIGHTS[None, :]).sum(axis=1)
        dv = (11 - soma % 11) % 11

        invalid_mask = _invalid_mask(batch, rows.shape[0])
        offset = draws.integers(11, 1, 11)
        dv = np.where(invalid_mask, (dv + offset) % 11, dv)

        digit_chars = index_matrix_to_chars(digits, _DIGITS)
        dv_chars = index_matrix_to_chars(dv[:, None], _RG_CHARS)
        char_matrix = np.concatenate([digit_chars, dv_chars], axis=1)
        layout = _rg_layout(column.format or "masked")
        return pa.array(format_layout(char_matrix, layout), type=pa.string())


def _rg_layout(fmt: str) -> list[int | str]:
    if fmt == "unmasked":
        return list(range(9))
    return [0, 1, ".", 2, 3, 4, ".", 5, 6, 7, "-", 8]


def is_valid_rg_sp(value: str) -> bool:
    """`True` se `value` (com ou sem máscara) satisfaz `soma + 100*DV ≡ 0 (mod 11)`
    do RG padrão SP (DD-01 A.3)."""
    normalized = _only_digits_and_x(value)
    if len(normalized) != 9:
        return False
    body, check = normalized[:8], normalized[8]
    if not body.isdigit() or check not in _RG_CHARS:
        return False
    digits = [int(char) for char in body]
    soma = sum(digit * weight for digit, weight in zip(digits, range(2, 10), strict=True))
    dv_value = 10 if check == "X" else int(check)
    return (soma + 100 * dv_value) % 11 == 0


# --- Cartão de crédito -----------------------------------------------------

_DEFAULT_BAD_OFFSET_SLOT = 19
_BRAND_SLOT_BASE = 20
_MAX_BRAND_SLOT = 62


@dataclass(frozen=True)
class CartaoCreditoGenerator:
    name: str = "cartao_credito"
    supports_invalid: bool = True
    supports_format: bool = True
    deterministic: bool = True
    draw_slots: int = 4

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def _brands(self, column: ColumnSpec) -> dict[str, bins_module.Brand]:
        raw_extra_bins = cast("tuple[dict[str, object], ...]", column.params.get("extra_bins", ()))
        return bins_module.with_extra_bins(bins_module.default_brands(), tuple(raw_extra_bins))

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"brands", "weights", "extra_bins"})
        all_brands = self._brands(column)
        requested_brands = get_param(column.params, "brands", list(all_brands))
        if not isinstance(requested_brands, list) or not requested_brands:
            errors.append(
                ValidationError(path="brands", message="'brands' deve ser uma lista não vazia")
            )
            requested_brands = []
        unknown_brands = sorted(set(requested_brands) - set(all_brands))
        if unknown_brands:
            errors.append(
                ValidationError(
                    path="brands", message=f"bandeira(s) desconhecida(s): {unknown_brands}"
                )
            )
        weights = column.params.get("weights")
        if weights is not None:
            errors += _check_weights(weights, requested_brands)
        for extra in cast("tuple[object, ...]", column.params.get("extra_bins", ())):
            errors += _check_extra_bin(extra)
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        max_length = 19 if (column.format or "masked") == "masked" else 16
        return logical.string(max_length, nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        rows = batch.rows
        row_count = rows.shape[0]
        all_brands = self._brands(column)
        requested_brands = get_param(column.params, "brands", list(all_brands))
        weights = _resolve_weights(column.params.get("weights"), requested_brands)

        candidates: list[tuple[str, bins_module.BinPrefix, int]] = [
            (brand_name, prefix, all_brands[brand_name].length)
            for brand_name in requested_brands
            for prefix in all_brands[brand_name].prefixes
        ]
        candidate_weights = np.array(
            [
                weights[requested_brands.index(brand_name)] / len(all_brands[brand_name].prefixes)
                for brand_name, _prefix, _length in candidates
            ]
        )
        candidate_pick = weighted_choice(draws, 2, candidate_weights)

        invalid_mask = _invalid_mask(batch, row_count)
        bad_offset = draws.integers(_DEFAULT_BAD_OFFSET_SLOT, 1, 10)

        fmt = column.format or "masked"
        max_len = max(length for _brand, _prefix, length in candidates)
        result = np.full(row_count, "", dtype=f"<U{max_len + 4}")
        for candidate_index, (_brand_name, prefix, length) in enumerate(candidates):
            mask = candidate_pick == candidate_index
            slot_base = _BRAND_SLOT_BASE + (2 * candidate_index) % (
                _MAX_BRAND_SLOT - _BRAND_SLOT_BASE
            )
            number = _candidate_number(draws, slot_base, prefix, length, invalid_mask, bad_offset)
            formatted = number if fmt == "unmasked" else _mask_card_number(number, length)
            result = np.where(mask, formatted, result)
        return pa.array(result, type=pa.string())


def _resolve_weights(raw_weights: object, brands: list[str]) -> NDArray[np.float64]:
    if raw_weights is None:
        return np.ones(len(brands), dtype=np.float64)
    if isinstance(raw_weights, dict):
        return np.array(
            [float(cast("float | int", raw_weights.get(brand, 1.0))) for brand in brands]
        )
    return np.array(
        [float(cast("float | int", value)) for value in cast("list[object]", raw_weights)]
    )


def _check_weights(weights: object, brands: list[str]) -> list[ValidationError]:
    if isinstance(weights, dict):
        unknown = sorted(set(weights) - set(brands))
        return (
            [
                ValidationError(
                    path="weights", message=f"pesos para bandeiras não selecionadas: {unknown}"
                )
            ]
            if unknown
            else []
        )
    if isinstance(weights, list):
        if len(weights) != len(brands):
            return [
                ValidationError(
                    path="weights", message="'weights' deve ter um peso por bandeira em 'brands'"
                )
            ]
        return []
    return [ValidationError(path="weights", message="'weights' deve ser lista ou objeto")]


def _check_extra_bin(extra: object) -> list[ValidationError]:
    if not isinstance(extra, dict) or not {"brand", "prefix", "length"} <= set(extra):
        return [
            ValidationError(
                path="extra_bins",
                message="cada item de 'extra_bins' precisa de brand, prefix e length",
            )
        ]
    return check_int(extra["length"], "extra_bins.length", minimum=1, maximum=19)


def _candidate_number(
    draws: Draws,
    slot_base: int,
    prefix: bins_module.BinPrefix,
    length: int,
    invalid_mask: NDArray[np.bool_],
    bad_offset: NDArray[np.int64],
) -> NDArray[np.str_]:
    row_count = draws.rows.shape[0]
    width = prefix.width
    if prefix.is_range:
        value = draws.integers(slot_base, int(prefix.start), int(prefix.end) + 1)
    else:
        value = np.full(row_count, int(prefix.start), dtype=np.int64)
    prefix_digits = digits_of(value, width)

    remaining = length - width - 1
    if remaining > 0:
        random_digits = draw_matrix(draws, slot_base + 1, remaining, 0, 10)
        partial = np.concatenate([prefix_digits, random_digits], axis=1)
    else:
        partial = prefix_digits

    check_digit = luhn_check_digit(partial)
    check_digit = np.where(invalid_mask, (check_digit + bad_offset) % 10, check_digit)
    full = np.concatenate([partial, check_digit[:, None]], axis=1)
    return join_columns(index_matrix_to_chars(full, _DIGITS))


def _mask_card_number(number: NDArray[np.str_], length: int) -> NDArray[np.str_]:
    row_count = number.shape[0]
    padded = np.ascontiguousarray(number).astype(f"<U{length}")
    char_matrix = padded.view("<U1").reshape(row_count, length)
    if length == 15:
        layout: list[int | str] = [*range(4), " ", *range(4, 10), " ", *range(10, 15)]
    else:
        layout = [*range(4), " ", *range(4, 8), " ", *range(8, 12), " ", *range(12, length)]
    return format_layout(char_matrix, layout)


def card_brand(value: str) -> str | None:
    """Bandeira cujo prefixo e comprimento casam com `value` (DD-01 A.4), sem checar
    Luhn. `None` se nenhuma bandeira padrão casar."""
    digits_text = re.sub(r"\D", "", value)
    for brand in bins_module.default_brands().values():
        if len(digits_text) != brand.length:
            continue
        for prefix in brand.prefixes:
            width = prefix.width
            candidate = digits_text[:width]
            if prefix.start <= candidate <= prefix.end:
                return brand.name
    return None
