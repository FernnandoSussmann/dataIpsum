"""Geradores primitivos da trilha A (DD-01 A.3): string, char, int, float, decimal,
boolean, date, time, timestamp, uuid, json e array."""

from __future__ import annotations

import json as json_module
import string as string_module
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING, cast

import numpy as np
import pyarrow as pa

import dataipsum.contracts.types as logical
from dataipsum.errors import ValidationError
from dataipsum.types.drawing import chars_from_pool, draw_matrix, truncate_to_lengths
from dataipsum.types.locales import Locale, resolve_locale
from dataipsum.types.params import (
    check_bool,
    check_float,
    check_int,
    check_str,
    get_param,
    unknown_params,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dataipsum.contracts.generator import GenContext, RowBatch
    from dataipsum.registry import Registry
    from dataipsum.schema.models import ColumnSpec
    from dataipsum.seeds import Draws

ALPHA = string_module.ascii_letters
ALNUM = string_module.ascii_letters + string_module.digits

_EPOCH_DATE = date(1970, 1, 1)
_MAX_DECIMAL_PRECISION = 38
_MAX_ARRAY_ITEMS = 1000
_MAX_JSON_FIELDS = 50
_MAX_JSON_DEPTH = 3


def _no_extra_deps(column: ColumnSpec) -> list[str]:
    return []


def _no_implied_columns(column: ColumnSpec) -> list[ColumnSpec]:
    return []


@dataclass(frozen=True)
class StringGenerator:
    """`string`: comprimento uniforme em `[min_length, max_length]` (DD-01 A.3)."""

    locales: Mapping[str, object]
    name: str = "string"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 2

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"min_length", "charset"})
        if column.max_length is None:
            errors.append(
                ValidationError(path="max_length", message="'max_length' é obrigatório em 'string'")
            )
        else:
            errors += check_int(column.max_length, "max_length", minimum=1, maximum=1_000_000)
        min_length = get_param(column.params, "min_length", 0)
        errors += check_int(min_length, "min_length", minimum=0)
        if (
            column.max_length is not None
            and isinstance(min_length, int)
            and min_length > column.max_length
        ):
            errors.append(
                ValidationError(
                    path="min_length", message="'min_length' não pode ser maior que 'max_length'"
                )
            )
        errors += check_str(
            get_param(column.params, "charset", "alpha"),
            "charset",
            allowed={"alpha", "alnum", "lorem"},
        )
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        return logical.string(column.max_length or 1, nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        max_length = column.max_length or 1
        min_length = get_param(column.params, "min_length", 0)
        charset = get_param(column.params, "charset", "alpha")
        lengths = draws.integers(2, min_length, max_length + 1)
        if charset == "lorem":
            values = _lorem_text(resolve_locale(self.locales, ctx.locale), draws, max_length)
        else:
            pool = ALPHA if charset == "alpha" else ALNUM
            matrix = draw_matrix(draws, 3, max_length, 0, len(pool))
            values = chars_from_pool(matrix, pool)
        return pa.array(truncate_to_lengths(values, lengths), type=pa.string())


def _lorem_text(locale: Locale, draws: Draws, max_length: int) -> np.ndarray:
    """Concatena palavras pt-BR com espaço até cobrir `max_length` caracteres.

    O número de palavras sorteadas é um limite superior seguro (assume palavras
    de 1 caractere) para garantir cobertura de `max_length` mesmo no pior caso,
    e é constante por coluna (não cresce com N).
    """
    word_count = max(1, (max_length + 2) // 2)
    words = locale.lorem_words
    matrix = draw_matrix(draws, 4, word_count, 0, len(words))
    word_array = np.array(words, dtype=object)
    columns = word_array[matrix]
    joined = columns[:, 0].astype(object)
    for column in range(1, word_count):
        joined = joined + " " + columns[:, column]
    return joined.astype(f"<U{max_length + word_count}")


@dataclass(frozen=True)
class CharGenerator:
    """`char`: comprimento fixo (DD-01 A.3)."""

    locales: Mapping[str, object]
    name: str = "char"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 1

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"length", "charset"})
        errors += check_int(get_param(column.params, "length", 1), "length", minimum=1, maximum=255)
        errors += check_str(
            get_param(column.params, "charset", "alpha"),
            "charset",
            allowed={"alpha", "alnum", "lorem"},
        )
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        length = get_param(column.params, "length", 1)
        return logical.char(length, nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        length = get_param(column.params, "length", 1)
        charset = get_param(column.params, "charset", "alpha")
        if charset == "lorem":
            lengths = np.full(batch.rows.shape[0], length, dtype=np.int64)
            values = _lorem_text(resolve_locale(self.locales, ctx.locale), draws, length)
            return pa.array(truncate_to_lengths(values, lengths), type=pa.string())
        pool = ALPHA if charset == "alpha" else ALNUM
        matrix = draw_matrix(draws, 2, length, 0, len(pool))
        return pa.array(chars_from_pool(matrix, pool), type=pa.string())


@dataclass(frozen=True)
class IntGenerator:
    """`int`: uniforme inteiro em `[min, max]` (DD-01 A.3)."""

    name: str = "int"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 1

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"min", "max"})
        minimum = get_param(column.params, "min", 0)
        maximum = get_param(column.params, "max", 2**31 - 1)
        errors += check_int(minimum, "min")
        errors += check_int(maximum, "max")
        if isinstance(minimum, int) and isinstance(maximum, int) and minimum > maximum:
            errors.append(ValidationError(path="min", message="'min' não pode ser maior que 'max'"))
        return errors

    def _bounds(self, column: ColumnSpec) -> tuple[int, int]:
        return get_param(column.params, "min", 0), get_param(column.params, "max", 2**31 - 1)

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        minimum, maximum = self._bounds(column)
        fits_int32 = minimum >= -(2**31) and maximum <= 2**31 - 1
        kind = logical.int32 if fits_int32 else logical.int64
        return kind(nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        minimum, maximum = self._bounds(column)
        values = draws.integers(2, minimum, maximum + 1)
        arrow_type = pa.int32() if self.logical_type(column).kind == "int32" else pa.int64()
        return pa.array(values, type=arrow_type)


@dataclass(frozen=True)
class FloatGenerator:
    """`float`: uniforme em `[min, max]`, arredondado se `decimals` (DD-01 A.3)."""

    name: str = "float"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 1

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"min", "max", "decimals"})
        minimum = get_param(column.params, "min", 0.0)
        maximum = get_param(column.params, "max", 1.0)
        errors += check_float(minimum, "min")
        errors += check_float(maximum, "max")
        if (
            isinstance(minimum, int | float)
            and isinstance(maximum, int | float)
            and minimum > maximum
        ):
            errors.append(ValidationError(path="min", message="'min' não pode ser maior que 'max'"))
        if "decimals" in column.params:
            errors += check_int(column.params["decimals"], "decimals", minimum=0, maximum=15)
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        return logical.float64(nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        minimum = get_param(column.params, "min", 0.0)
        maximum = get_param(column.params, "max", 1.0)
        decimals = cast("int | None", column.params.get("decimals"))
        values = minimum + draws.uniform(2) * (maximum - minimum)
        if decimals is not None:
            values = np.round(values, decimals)
        return pa.array(values, type=pa.float64())


@dataclass(frozen=True)
class DecimalGenerator:
    """`decimal`: valor exato, sorteado como inteiro não escalado (DD-01 A.3)."""

    name: str = "decimal"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 1

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"precision", "scale", "min", "max"})
        precision = get_param(column.params, "precision", 10)
        scale = get_param(column.params, "scale", 2)
        errors += check_int(precision, "precision", minimum=1, maximum=_MAX_DECIMAL_PRECISION)
        errors += check_int(scale, "scale", minimum=0)
        if isinstance(precision, int) and isinstance(scale, int) and scale > precision:
            errors.append(
                ValidationError(path="scale", message="'scale' não pode ser maior que 'precision'")
            )
        for bound_name in ("min", "max"):
            if bound_name in column.params:
                errors += check_str(column.params[bound_name], bound_name)
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        precision = get_param(column.params, "precision", 10)
        scale = get_param(column.params, "scale", 2)
        return logical.decimal(precision, scale, nullable=column.null_ratio > 0)

    def _unscaled_bounds(self, column: ColumnSpec) -> tuple[int, int]:
        scale = get_param(column.params, "scale", 2)
        precision = get_param(column.params, "precision", 10)
        default_min = 0
        # `seeds.integers` sorteia o deslocamento em `[0, span)` sobre inteiros de
        # 64 bits (rejeição de Lemire, DD-00 §3.6): `span` precisa caber num
        # `uint64`. Sem `min`/`max` explícitos, um `precision` grande (até 38)
        # produziria um span de até 10**38, muito maior que 2**64. Nesse caso o
        # teto sintético fica em 2**63-2; para a faixa completa de `precision`,
        # o usuário informa `min`/`max` (strings), que já produzem um span menor.
        default_max = min(10**precision - 1, 2**63 - 2)
        minimum_str = cast("str | None", column.params.get("min"))
        maximum_str = cast("str | None", column.params.get("max"))
        minimum = default_min if minimum_str is None else _unscale(minimum_str, scale)
        maximum = default_max if maximum_str is None else _unscale(maximum_str, scale)
        return minimum, maximum

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        precision = get_param(column.params, "precision", 10)
        scale = get_param(column.params, "scale", 2)
        minimum, maximum = self._unscaled_bounds(column)
        unscaled = draws.integers(2, minimum, maximum + 1)
        from decimal import Decimal as PyDecimal

        quantum = PyDecimal(1).scaleb(-scale)
        exact = [PyDecimal(int(value)).scaleb(-scale).quantize(quantum) for value in unscaled]
        return pa.array(exact, type=pa.decimal128(precision, scale))


def _unscale(value: str, scale: int) -> int:
    from decimal import Decimal as PyDecimal

    return int((PyDecimal(value) * (10**scale)).to_integral_value())


@dataclass(frozen=True)
class BooleanGenerator:
    """`boolean`: `uniform < true_ratio` (DD-01 A.3)."""

    name: str = "boolean"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 1

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"true_ratio"})
        errors += check_float(
            get_param(column.params, "true_ratio", 0.5), "true_ratio", minimum=0.0, maximum=1.0
        )
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        return logical.boolean(nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        true_ratio = get_param(column.params, "true_ratio", 0.5)
        values = draws.uniform(2) < true_ratio
        return pa.array(values, type=pa.bool_())


@dataclass(frozen=True)
class DateGenerator:
    """`date`: dia uniforme em `[min, max]` (DD-01 A.3)."""

    name: str = "date"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 1

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"min", "max"})
        minimum = get_param(column.params, "min", "2000-01-01")
        maximum = get_param(column.params, "max", "2030-12-31")
        errors += _check_iso_date(minimum, "min")
        errors += _check_iso_date(maximum, "max")
        if not errors and date.fromisoformat(minimum) > date.fromisoformat(maximum):
            errors.append(ValidationError(path="min", message="'min' não pode ser depois de 'max'"))
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        return logical.date(nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        minimum = date.fromisoformat(get_param(column.params, "min", "2000-01-01"))
        maximum = date.fromisoformat(get_param(column.params, "max", "2030-12-31"))
        min_ordinal = (minimum - _EPOCH_DATE).days
        max_ordinal = (maximum - _EPOCH_DATE).days
        offsets = draws.integers(2, min_ordinal, max_ordinal + 1)
        return pa.array(offsets.astype(np.int32), type=pa.date32())


def _check_iso_date(value: object, name: str) -> list[ValidationError]:
    if not isinstance(value, str):
        return [ValidationError(path=name, message=f"'{name}' deve ser uma data ISO 'AAAA-MM-DD'")]
    try:
        date.fromisoformat(value)
    except ValueError:
        return [
            ValidationError(path=name, message=f"'{name}' não é uma data ISO válida: '{value}'")
        ]
    return []


@dataclass(frozen=True)
class TimeGenerator:
    """`time`: uniforme em `[min, max]` (DD-01 A.3)."""

    name: str = "time"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 1

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"min", "max", "precision"})
        errors += _check_iso_time(get_param(column.params, "min", "00:00:00"), "min")
        errors += _check_iso_time(get_param(column.params, "max", "23:59:59"), "max")
        errors += check_str(
            get_param(column.params, "precision", "s"), "precision", allowed={"s", "ms"}
        )
        if not errors:
            minimum = time.fromisoformat(get_param(column.params, "min", "00:00:00"))
            maximum = time.fromisoformat(get_param(column.params, "max", "23:59:59"))
            if minimum > maximum:
                errors.append(
                    ValidationError(path="min", message="'min' não pode ser depois de 'max'")
                )
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        return logical.time(nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        minimum = time.fromisoformat(get_param(column.params, "min", "00:00:00"))
        maximum = time.fromisoformat(get_param(column.params, "max", "23:59:59"))
        precision = get_param(column.params, "precision", "s")
        unit = 1000 if precision == "ms" else 1

        def to_units(value: time) -> int:
            seconds = value.hour * 3600 + value.minute * 60 + value.second
            return seconds * unit + (value.microsecond // 1000 if precision == "ms" else 0)

        min_units = to_units(minimum)
        max_units = to_units(maximum)
        offsets = draws.integers(2, min_units, max_units + 1)
        arrow_unit = "ms" if precision == "ms" else "s"
        return pa.array(offsets.astype(np.int32), type=pa.time32(arrow_unit))


def _check_iso_time(value: object, name: str) -> list[ValidationError]:
    if not isinstance(value, str):
        return [ValidationError(path=name, message=f"'{name}' deve ser um horário ISO 'HH:MM:SS'")]
    try:
        time.fromisoformat(value)
    except ValueError:
        return [
            ValidationError(path=name, message=f"'{name}' não é um horário ISO válido: '{value}'")
        ]
    return []


@dataclass(frozen=True)
class TimestampGenerator:
    """`timestamp`: uniforme em milissegundos (DD-01 A.3)."""

    name: str = "timestamp"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 1

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"min", "max", "timezone"})
        errors += _check_iso_timestamp(
            get_param(column.params, "min", "2000-01-01T00:00:00Z"), "min"
        )
        errors += _check_iso_timestamp(
            get_param(column.params, "max", "2030-12-31T23:59:59Z"), "max"
        )
        errors += check_bool(get_param(column.params, "timezone", False), "timezone")
        return errors

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        return logical.timestamp(
            tz=bool(get_param(column.params, "timezone", False)), nullable=column.null_ratio > 0
        )

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        minimum = _parse_iso_timestamp(get_param(column.params, "min", "2000-01-01T00:00:00Z"))
        maximum = _parse_iso_timestamp(get_param(column.params, "max", "2030-12-31T23:59:59Z"))
        min_ms = int(minimum.timestamp() * 1000)
        max_ms = int(maximum.timestamp() * 1000)
        offsets = draws.integers(2, min_ms, max_ms + 1)
        has_tz = bool(get_param(column.params, "timezone", False))
        return pa.array(offsets, type=pa.timestamp("ms", tz="UTC" if has_tz else None))


def _check_iso_timestamp(value: object, name: str) -> list[ValidationError]:
    if not isinstance(value, str):
        return [ValidationError(path=name, message=f"'{name}' deve ser um timestamp ISO 8601")]
    try:
        _parse_iso_timestamp(value)
    except ValueError:
        return [
            ValidationError(
                path=name, message=f"'{name}' não é um timestamp ISO 8601 válido: '{value}'"
            )
        ]
    return []


def _parse_iso_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class UuidGenerator:
    """`uuid`: 128 bits de dois slots, versão 4 e variante RFC 4122 (DD-01 A.3)."""

    name: str = "uuid"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 2

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        return unknown_params(column.params, set())

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        return logical.uuid(nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        from dataipsum.seeds import draw_u64
        from dataipsum.types.drawing import format_layout, index_matrix_to_chars

        high = draw_u64(draws.seed_col, draws.rows, 2)
        low = draw_u64(draws.seed_col, draws.rows, 3)
        high = (high & np.uint64(0xFFFFFFFFFFFF0FFF)) | np.uint64(0x0000000000004000)
        low = (low & np.uint64(0x3FFFFFFFFFFFFFFF)) | np.uint64(0x8000000000000000)

        nibble_shifts = np.arange(15, -1, -1, dtype=np.uint64) * np.uint64(4)
        high_nibbles = (high[:, None] >> nibble_shifts[None, :]) & np.uint64(0xF)
        low_nibbles = (low[:, None] >> nibble_shifts[None, :]) & np.uint64(0xF)
        nibbles = np.concatenate([high_nibbles, low_nibbles], axis=1).astype(np.int64)

        char_matrix = index_matrix_to_chars(nibbles, "0123456789abcdef")
        layout: list[int | str] = [
            *range(8),
            "-",
            *range(8, 12),
            "-",
            *range(12, 16),
            "-",
            *range(16, 20),
            "-",
            *range(20, 32),
        ]
        formatted = format_layout(char_matrix, layout)
        return pa.array(formatted, type=pa.string())


_PRIMITIVE_TYPE_NAMES = frozenset(
    {"string", "char", "int", "float", "decimal", "boolean", "date", "time", "timestamp", "uuid"}
)


@dataclass(frozen=True)
class JsonGenerator:
    """`json`: objeto serializado com os campos declarados em `params.fields` (DD-01 A.3)."""

    registry: Registry
    name: str = "json"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 0

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"fields", "max_depth"})
        fields = column.params.get("fields")
        if not isinstance(fields, dict) or not (1 <= len(fields) <= _MAX_JSON_FIELDS):
            errors.append(
                ValidationError(
                    path="fields", message=f"'fields' deve ter de 1 a {_MAX_JSON_FIELDS} campos"
                )
            )
            fields = {}
        max_depth = get_param(column.params, "max_depth", _MAX_JSON_DEPTH)
        errors += check_int(max_depth, "max_depth", minimum=1, maximum=_MAX_JSON_DEPTH)
        for field_name, field_spec in fields.items():
            errors += self._validate_field(field_name, field_spec, depth=1, max_depth=max_depth)
        return errors

    def _validate_field(
        self, field_name: str, field_spec: object, *, depth: int, max_depth: int
    ) -> list[ValidationError]:
        prefix = f"fields.{field_name}"
        if not isinstance(field_spec, dict) or "type" not in field_spec:
            return [ValidationError(path=prefix, message="campo precisa de 'type'")]
        field_type = field_spec["type"]
        field_params = field_spec.get("params", {})
        if field_type not in _PRIMITIVE_TYPE_NAMES:
            return [
                ValidationError(
                    path=f"{prefix}.type",
                    message=f"tipo de campo JSON deve ser primitivo, recebido: '{field_type}'",
                )
            ]
        if depth > max_depth:
            return [ValidationError(path=prefix, message="'max_depth' excedido")]
        sub_generator = self.registry.get_generator(cast(str, field_type))()
        fake_column = _fake_column(
            cast(str, field_type),
            cast("Mapping[str, object]", field_params),
            cast("int | None", field_spec.get("max_length")),
        )
        return [
            ValidationError(
                path=f"{prefix}.params.{sub.path}" if sub.path else f"{prefix}.params",
                message=sub.message,
            )
            for sub in sub_generator.validate_params(fake_column, None)
        ]

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        return logical.json(nullable=column.null_ratio > 0)

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        from dataipsum.seeds import derive

        fields: dict[str, dict[str, object]] = get_param(column.params, "fields", {})
        field_values: dict[str, list[object]] = {}
        for field_name, field_spec in fields.items():
            field_type = cast(str, field_spec["type"])
            field_params = cast("Mapping[str, object]", field_spec.get("params", {}))
            sub_generator = self.registry.get_generator(field_type)()
            fake_column = _fake_column(
                field_type, field_params, cast("int | None", field_spec.get("max_length"))
            )
            field_seed = derive(draws.seed_col, f"json:{field_name}")
            from dataipsum.seeds import Draws as DrawsClass

            sub_draws = DrawsClass(seed_col=field_seed, rows=batch.rows)
            sub_array = sub_generator.generate(fake_column, batch, sub_draws, ctx)
            field_values[field_name] = sub_array.to_pylist()
        row_count = batch.rows.shape[0]
        objects = (
            {name: field_values[name][index] for name in fields} for index in range(row_count)
        )
        texts = (json_module.dumps(obj, ensure_ascii=False, allow_nan=False) for obj in objects)
        return pa.array(list(texts), type=pa.string())


def _fake_column(
    field_type: str, field_params: Mapping[str, object], max_length: int | None = None
) -> ColumnSpec:
    from dataipsum.schema.models import ColumnSpec as RealColumnSpec

    return RealColumnSpec(
        name="_nested_field", type=field_type, params=dict(field_params), max_length=max_length
    )


@dataclass(frozen=True)
class ArrayGenerator:
    """`array`: lista de itens de um tipo primitivo (DD-01 A.3)."""

    registry: Registry
    name: str = "array"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 1

    depends_on = staticmethod(_no_extra_deps)
    implied_columns = staticmethod(_no_implied_columns)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        errors = unknown_params(column.params, {"items", "min_items", "max_items"})
        items = column.params.get("items")
        if not isinstance(items, dict) or "type" not in items:
            errors.append(ValidationError(path="items", message="'items' precisa de 'type'"))
        elif items["type"] not in _PRIMITIVE_TYPE_NAMES:
            errors.append(
                ValidationError(
                    path="items.type",
                    message=f"tipo de item deve ser primitivo, recebido: '{items['type']}'",
                )
            )
        min_items = get_param(column.params, "min_items", 0)
        max_items = get_param(column.params, "max_items", 10)
        errors += check_int(min_items, "min_items", minimum=0)
        errors += check_int(max_items, "max_items", minimum=0, maximum=_MAX_ARRAY_ITEMS)
        if isinstance(min_items, int) and isinstance(max_items, int) and min_items > max_items:
            errors.append(
                ValidationError(
                    path="min_items", message="'min_items' não pode ser maior que 'max_items'"
                )
            )
        return errors

    def _item_logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        items: Mapping[str, object] = get_param(column.params, "items", {"type": "string"})
        item_type = cast(str, items["type"])
        sub_generator = self.registry.get_generator(item_type)()
        fake_column = _fake_column(
            item_type,
            cast("Mapping[str, object]", items.get("params", {})),
            cast("int | None", items.get("max_length")),
        )
        return cast(logical.LogicalType, sub_generator.logical_type(fake_column))

    def logical_type(self, column: ColumnSpec) -> logical.LogicalType:
        max_items = get_param(column.params, "max_items", 10)
        return logical.array(
            self._item_logical_type(column), max_items, nullable=column.null_ratio > 0
        )

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        from dataipsum.seeds import Draws as DrawsClass
        from dataipsum.seeds import derive

        items: Mapping[str, object] = get_param(column.params, "items", {"type": "string"})
        min_items = get_param(column.params, "min_items", 0)
        max_items = get_param(column.params, "max_items", 10)
        item_type = cast(str, items["type"])
        item_params = cast("Mapping[str, object]", items.get("params", {}))
        sub_generator = self.registry.get_generator(item_type)()
        fake_column = _fake_column(
            item_type, item_params, cast("int | None", items.get("max_length"))
        )

        counts = draws.integers(2, min_items, max_items + 1)
        item_seed = derive(draws.seed_col, "array:item")
        item_type_arrow = sub_generator.logical_type(fake_column)

        slot_values: list[pa.Array] = []
        for slot in range(max_items):
            slot_seed = derive(item_seed, f"slot:{slot}")
            sub_draws = DrawsClass(seed_col=slot_seed, rows=batch.rows)
            slot_values.append(sub_generator.generate(fake_column, batch, sub_draws, ctx))

        row_count = batch.rows.shape[0]
        lists = [
            [slot_values[slot][row].as_py() for slot in range(counts[row])]
            for row in range(row_count)
        ]
        return pa.array(lists, type=pa.list_(logical.to_arrow_type(item_type_arrow)))
