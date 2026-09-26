"""Geradores `nome_proprio` e `email` (DD-01 A.3), com `is_valid_email` (A.4).

O corpo de um e-mail (o texto) é assunto da trilha C (`llm_email`); aqui só o
**endereço**, sintaticamente válido por padrão.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from numpy.typing import NDArray

import dataipsum.contracts.types as logical
from dataipsum.errors import ValidationError
from dataipsum.seeds import Draws
from dataipsum.types.drawing import digits_of, index_matrix_to_chars, join_columns
from dataipsum.types.locales import Locale, resolve_locale
from dataipsum.types.params import check_bool, check_str, get_param, unknown_params

if TYPE_CHECKING:
    from dataipsum.contracts.generator import GenContext, RowBatch
    from dataipsum.schema.models import ColumnSpec

logger = logging.getLogger("dataipsum.types.person")

_NOME_MAX_LENGTH_DEFAULT = 120
_NOME_LENGTH_RETRY_ATTEMPTS = 8
_ACCENT_MARKS_PATTERN = f"[{chr(0x0300)}-{chr(0x036F)}]"

_RESERVED_DOMAINS = ("example.com", "example.net", "example.org")
_RESERVED_EXACT = frozenset({"example.com", "example.net", "example.org", "example.edu"})
_RESERVED_SUFFIXES = (".example", ".test", ".invalid", ".localhost")

_LOCAL_PART_RE = re.compile(r"^[a-z0-9]+([._][a-z0-9]+)*$")
_DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

_LOCAL_MAX_LENGTH = 64
_EMAIL_MAX_LENGTH_CEILING = 254
_UNIQUE_SUFFIX_WIDTH = 13
_BASE36_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"

_INVALID_VARIANTS = (
    "sem_arroba",
    "dois_arroba",
    "ponto_duplo",
    "comeca_com_ponto",
    "dominio_sem_tld",
    "espaco",
)


def _no_extra_deps(column: ColumnSpec) -> list[str]:
    return []


def _no_implied_columns(column: ColumnSpec) -> list[ColumnSpec]:
    return []


# --- nome_proprio ----------------------------------------------------------


@dataclass(frozen=True)
class NomeProprioGenerator:
    locales: Mapping[str, object]
    name: str = "nome_proprio"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 6

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"gender", "parts"})
        errors += check_str(
            get_param(column.params, "gender", "any"), "gender", allowed={"any", "f", "m"}
        )
        errors += check_str(
            get_param(column.params, "parts", "full"), "parts", allowed={"first", "full"}
        )
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        max_length = column.max_length or _NOME_MAX_LENGTH_DEFAULT
        return logical.string(max_length, nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        locale = resolve_locale(self.locales, ctx.locale)
        gender_param = get_param(column.params, "gender", "any")
        parts = get_param(column.params, "parts", "full")
        max_length = column.max_length or _NOME_MAX_LENGTH_DEFAULT

        rows = draws.rows
        result: NDArray[np.object_] = np.empty(rows.shape[0], dtype=object)
        pending = np.ones(rows.shape[0], dtype=np.bool_)

        for attempt in range(_NOME_LENGTH_RETRY_ATTEMPTS + 1):
            pending_positions = np.flatnonzero(pending)
            if pending_positions.size == 0:
                break
            attempt_draws = Draws(seed_col=draws.seed_col, rows=rows[pending_positions])
            candidate = _candidate_names(locale, gender_param, parts, attempt_draws, attempt)
            fits = np.char.str_len(candidate.astype(str)) <= max_length
            accepted = pending_positions[fits]
            result[accepted] = candidate[fits]
            pending[accepted] = False

        if pending.any():
            pending_positions = np.flatnonzero(pending)
            attempt_draws = Draws(seed_col=draws.seed_col, rows=rows[pending_positions])
            candidate = _candidate_names(
                locale, gender_param, parts, attempt_draws, _NOME_LENGTH_RETRY_ATTEMPTS + 1
            )
            truncated = _truncate_at_word_boundary(pa.array(candidate.tolist()), max_length)
            result[pending_positions] = np.array(truncated.to_pylist(), dtype=object)

        return pa.array(result.tolist(), type=pa.string())


def _candidate_names(
    locale: Locale, gender_param: str, parts: str, draws: Draws, attempt: int
) -> NDArray[np.object_]:
    n = draws.rows.shape[0]
    slot = 2 + attempt * 6
    if gender_param == "f":
        gender_pick = np.zeros(n, dtype=np.int64)
    elif gender_param == "m":
        gender_pick = np.ones(n, dtype=np.int64)
    else:
        gender_pick = draws.integers(slot, 0, 2)

    first_f_pool = np.array(locale.first_names_f, dtype=object)
    first_m_pool = np.array(locale.first_names_m, dtype=object)
    first_f = first_f_pool[draws.integers(slot + 1, 0, len(first_f_pool))]
    first_m = first_m_pool[draws.integers(slot + 2, 0, len(first_m_pool))]
    first = np.where(gender_pick == 0, first_f, first_m)

    if parts == "first":
        return first.astype(object)

    last_pool = np.array(locale.last_names, dtype=object)
    surname_count = draws.integers(slot + 3, 1, 3)
    surname1 = last_pool[draws.integers(slot + 4, 0, len(last_pool))]
    surname2 = last_pool[draws.integers(slot + 5, 0, len(last_pool))]

    full = first.astype(object) + " " + surname1
    full = np.where(surname_count == 2, full + " " + surname2, full)
    return cast("NDArray[np.object_]", full.astype(object))


def _truncate_at_word_boundary(names: pa.Array, max_length: int) -> pa.Array:
    was_truncated = pc.greater(pc.utf8_length(names), max_length)
    hard = pc.utf8_slice_codeunits(names, 0, max_length)
    trimmed = pc.utf8_trim_whitespace(
        pc.replace_substring_regex(hard, pattern=r"\S*$", replacement="")
    )
    trimmed_or_hard = pc.if_else(pc.equal(trimmed, ""), hard, trimmed)
    return pc.if_else(was_truncated, trimmed_or_hard, names)


# --- email -------------------------------------------------------------


@dataclass(frozen=True)
class EmailGenerator:
    locales: Mapping[str, object]
    name: str = "email"
    supports_invalid: bool = True
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 6

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"domains", "name_column", "unique"})
        domains = get_param(column.params, "domains", list(_RESERVED_DOMAINS))
        errors += _check_domains(domains)
        name_column = column.params.get("name_column")
        if name_column is not None:
            errors += check_str(name_column, "name_column")
        errors += check_bool(get_param(column.params, "unique", False), "unique")
        max_length = column.max_length or _EMAIL_MAX_LENGTH_CEILING
        if max_length > _EMAIL_MAX_LENGTH_CEILING:
            errors.append(
                ValidationError(
                    path="max_length",
                    message=(
                        f"'max_length' não pode passar de {_EMAIL_MAX_LENGTH_CEILING} em 'email'"
                    ),
                )
            )
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        max_length = column.max_length or _EMAIL_MAX_LENGTH_CEILING
        return logical.string(max_length, nullable=column.null_ratio > 0)

    def depends_on(self, column: ColumnSpec) -> list[str]:
        name_column = column.params.get("name_column")
        return [name_column] if isinstance(name_column, str) else []

    implied_columns = staticmethod(_no_implied_columns)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        locale = resolve_locale(self.locales, ctx.locale)
        domains = get_param(column.params, "domains", list(_RESERVED_DOMAINS))
        name_column = column.params.get("name_column")
        unique = bool(get_param(column.params, "unique", False))
        max_length = column.max_length or _EMAIL_MAX_LENGTH_CEILING

        base_names = _resolve_base_names(name_column, ctx, draws)
        fallback = _fallback_full_names(locale, draws)
        effective_names = pc.if_else(pc.is_null(base_names), fallback, base_names)
        first, last = _extract_first_last(effective_names)

        separator_pool = np.array([".", "_", ""], dtype=object)
        separator = pa.array(separator_pool[draws.integers(4, 0, 3)])
        local = pc.binary_join_element_wise(first, last, separator)

        has_digits = draws.uniform(5) < 0.3
        digit_values = draws.integers(6, 0, 100)
        digit_suffix = pa.array(
            join_columns(index_matrix_to_chars(digits_of(digit_values, 2), "0123456789"))
        )
        local = pc.if_else(
            pa.array(has_digits), pc.binary_join_element_wise(local, digit_suffix, ""), local
        )

        suffix = _unique_suffix(draws.rows) if unique else None
        local_budget = _LOCAL_MAX_LENGTH - (_UNIQUE_SUFFIX_WIDTH + 1 if unique else 0)
        local = pc.utf8_slice_codeunits(local, 0, local_budget)
        if suffix is not None:
            local = pc.binary_join_element_wise(local, suffix, "")

        domain_pool = np.array(domains, dtype=object)
        domain = pa.array(domain_pool[draws.integers(7, 0, len(domain_pool))])

        valid_address = pc.binary_join_element_wise(local, domain, "@")
        valid_address = pc.utf8_slice_codeunits(valid_address, 0, max_length)

        invalid_mask = batch.invalid_mask
        if invalid_mask is None or not invalid_mask.any():
            return valid_address

        variants = _invalid_variants(local, domain)
        variant_pick = draws.choice(8, len(_INVALID_VARIANTS))
        chosen = valid_address
        for index, variant_name in enumerate(_INVALID_VARIANTS):
            mask = invalid_mask & (variant_pick == index)
            chosen = pc.if_else(pa.array(mask), variants[variant_name], chosen)
        return chosen


def _resolve_base_names(name_column: object, ctx: GenContext, draws: Draws) -> pa.Array:
    if not isinstance(name_column, str):
        return pa.nulls(draws.rows.shape[0], type=pa.string())
    same_row = ctx.same_row([name_column])
    return pa.array(same_row[name_column].to_pylist(), type=pa.string())


def _fallback_full_names(locale: Locale, draws: Draws) -> pa.Array:
    first_pool = np.array(locale.first_names_any, dtype=object)
    last_pool = np.array(locale.last_names, dtype=object)
    first = first_pool[draws.integers(2, 0, len(first_pool))]
    last = last_pool[draws.integers(3, 0, len(last_pool))]
    full = np.char.add(np.char.add(first.astype(str), " "), last.astype(str))
    return pa.array(full)


def _extract_first_last(names: pa.Array) -> tuple[pa.Array, pa.Array]:
    normalized = pc.utf8_lower(pc.utf8_normalize(names, "NFKD"))
    stripped = pc.replace_substring_regex(normalized, pattern=_ACCENT_MARKS_PATTERN, replacement="")
    cleaned = pc.replace_substring_regex(stripped, pattern=r"[^a-z0-9\s]", replacement="")
    trimmed = pc.utf8_trim_whitespace(
        pc.replace_substring_regex(cleaned, pattern=r"\s+", replacement=" ")
    )
    first = pc.extract_regex(trimmed, pattern=r"^(?P<value>[a-z0-9]+)").field("value")
    last = pc.extract_regex(trimmed, pattern=r"(?P<value>[a-z0-9]+)$").field("value")
    return pc.fill_null(first, "user"), pc.fill_null(last, "user")


def _unique_suffix(rows: NDArray[np.int64]) -> pa.Array:
    digits = digits_of(rows, _UNIQUE_SUFFIX_WIDTH, base=36)
    chars = index_matrix_to_chars(digits, _BASE36_ALPHABET)
    return pa.array(np.char.add(".", join_columns(chars)))


def _invalid_variants(local: pa.Array, domain: pa.Array) -> dict[str, pa.Array]:
    domain_without_tld = pc.extract_regex(domain, pattern=r"^(?P<value>[^.]+)").field("value")
    local_first = pc.utf8_slice_codeunits(local, 0, 1)
    local_rest = pc.utf8_slice_codeunits(local, 1, None)
    return {
        "sem_arroba": pc.binary_join_element_wise(local, domain, ""),
        "dois_arroba": pc.binary_join_element_wise(local, domain, "@@"),
        "ponto_duplo": pc.binary_join_element_wise(
            pc.binary_join_element_wise(local_first, local_rest, ".."), domain, "@"
        ),
        "comeca_com_ponto": pc.binary_join_element_wise(
            pc.binary_join_element_wise("", local, "."), domain, "@"
        ),
        "dominio_sem_tld": pc.binary_join_element_wise(local, domain_without_tld, "@"),
        "espaco": pc.binary_join_element_wise(
            pc.binary_join_element_wise(local_first, local_rest, " "), domain, "@"
        ),
    }


def _is_reserved_domain(domain: str) -> bool:
    lowered = domain.lower()
    return lowered in _RESERVED_EXACT or lowered.endswith(_RESERVED_SUFFIXES)


def _check_domains(domains: object) -> list[ValidationError]:
    if not isinstance(domains, list) or not domains:
        return [ValidationError(path="domains", message="'domains' deve ser uma lista não vazia")]
    invalid = [domain for domain in domains if not _is_syntactically_valid_domain(domain)]
    if invalid:
        return [
            ValidationError(
                path="domains", message=f"domínio(s) sintaticamente inválido(s): {invalid}"
            )
        ]
    non_reserved = [domain for domain in domains if not _is_reserved_domain(domain)]
    if non_reserved:
        logger.warning(
            "domínio(s) de e-mail não reservado(s) pela RFC 2606: %s. "
            "Os endereços gerados podem existir de verdade.",
            non_reserved,
        )
    return []


def _is_syntactically_valid_domain(domain: object) -> bool:
    if not isinstance(domain, str):
        return False
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    if not all(_DOMAIN_LABEL_RE.fullmatch(label) for label in labels):
        return False
    tld = labels[-1]
    return tld.isalpha() and len(tld) >= 2


def is_valid_email(value: str) -> bool:
    """`True` se `value` é um endereço sintaticamente válido (DD-01 A.3), com no
    máximo 254 caracteres no total e 64 na parte local."""
    if len(value) > _EMAIL_MAX_LENGTH_CEILING or value.count("@") != 1:
        return False
    local, domain = value.split("@")
    if not local or len(local) > _LOCAL_MAX_LENGTH or not _LOCAL_PART_RE.fullmatch(local):
        return False
    return _is_syntactically_valid_domain(domain)
