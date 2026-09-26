"""Validação de parâmetros dos geradores da trilha A (DD-01 A.5).

Cada função devolve uma lista de `ValidationError` (vazia se o parâmetro é
válido), com `path` relativo ao nome do parâmetro: o chamador (`ColumnSpec`
validation em `schema/models.py`) já prefixa com `tables[i].columns[j].params.`.
"""

from __future__ import annotations

from collections.abc import Mapping, Set
from typing import cast

from dataipsum.errors import ValidationError


def get_param[T](params: Mapping[str, object], name: str, default: T) -> T:
    """Lê `params[name]` já tipado como `default` (mesmo tipo esperado pelo `Generator`).

    `column.params` é `dict[str, object]` (DD-00 §3.3: "objeto livre"); em
    tempo de `generate`, o valor já passou por `validate_params`, então o
    `cast` só ajusta a visão estática, sem checagem em runtime.
    """
    return cast(T, params.get(name, default))


def unknown_params(params: Mapping[str, object], allowed: Set[str]) -> list[ValidationError]:
    return [
        ValidationError(path=name, message=f"parâmetro desconhecido: '{name}'")
        for name in sorted(set(params) - set(allowed))
    ]


def check_int(
    value: object,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> list[ValidationError]:
    if not isinstance(value, int) or isinstance(value, bool):
        return [ValidationError(path=name, message=f"'{name}' deve ser inteiro")]
    errors = []
    if minimum is not None and value < minimum:
        errors.append(ValidationError(path=name, message=f"'{name}' deve ser >= {minimum}"))
    if maximum is not None and value > maximum:
        errors.append(ValidationError(path=name, message=f"'{name}' deve ser <= {maximum}"))
    return errors


def check_float(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> list[ValidationError]:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return [ValidationError(path=name, message=f"'{name}' deve ser numérico")]
    errors = []
    if minimum is not None and value < minimum:
        errors.append(ValidationError(path=name, message=f"'{name}' deve ser >= {minimum}"))
    if maximum is not None and value > maximum:
        errors.append(ValidationError(path=name, message=f"'{name}' deve ser <= {maximum}"))
    return errors


def check_str(
    value: object, name: str, *, allowed: Set[str] | None = None
) -> list[ValidationError]:
    if not isinstance(value, str):
        return [ValidationError(path=name, message=f"'{name}' deve ser texto")]
    if allowed is not None and value not in allowed:
        options = ", ".join(sorted(allowed))
        return [ValidationError(path=name, message=f"'{name}' deve ser um de: {options}")]
    return []


def check_bool(value: object, name: str) -> list[ValidationError]:
    if not isinstance(value, bool):
        return [ValidationError(path=name, message=f"'{name}' deve ser booleano")]
    return []
