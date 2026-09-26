"""Algoritmo de Luhn (DD-01 A.3, `cartao_credito`): cálculo vetorizado do dígito
verificador e verificação escalar reutilizável (`luhn_is_valid`, DD-01 A.4)."""

from __future__ import annotations

import re

import numpy as np
from numpy.typing import NDArray

_NON_DIGIT = re.compile(r"\D")


def luhn_check_digit(partial_digits: NDArray[np.int64]) -> NDArray[np.int64]:
    """Dígito verificador de Luhn para `partial_digits` (`(N, L)`, mais significativo
    primeiro), tal que `partial_digits` seguido do dígito devolvido é válido."""
    width = partial_digits.shape[1]
    distance_from_check_digit = np.arange(width, 0, -1)
    doubled_positions = (distance_from_check_digit % 2) == 1
    doubled = partial_digits * 2
    doubled = np.where(doubled > 9, doubled - 9, doubled)
    contribution = np.where(doubled_positions[None, :], doubled, partial_digits)
    total = contribution.sum(axis=1)
    return (10 - (total % 10)) % 10


def _luhn_total(digits: list[int]) -> int:
    """Soma de Luhn do número **completo** (dígito verificador incluído): o
    dígito verificador (posição 1, a partir da direita) nunca é dobrado; a
    posição 2 (o dígito imediatamente à esquerda) é a primeira dobrada."""
    distances_from_right = range(len(digits), 0, -1)
    contributions = (
        (digit * 2 - 9 if digit * 2 > 9 else digit * 2) if distance % 2 == 0 else digit
        for digit, distance in zip(digits, distances_from_right, strict=True)
    )
    return sum(contributions)


def luhn_is_valid(value: str) -> bool:
    """`True` se `value` (com ou sem separadores) passa no algoritmo de Luhn."""
    digits_text = _NON_DIGIT.sub("", value)
    if not digits_text:
        return False
    digits = [int(char) for char in digits_text]
    return _luhn_total(digits) % 10 == 0
