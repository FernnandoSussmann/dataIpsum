"""Plugin mínimo de exemplo: gerador `exemplo_placa` (DD-00 §7.2, §3.4).

Demonstra a estrutura de um plugin externo: implementa o Protocol
`dataipsum.contracts.generator.Generator` e se registra via o grupo de entry
points `dataipsum.generators` (ver `pyproject.toml` deste pacote), em vez de
chamar `registry.register_generator` diretamente — só plugins *internos*
(`types`, `relations`, `llm`, `sinks`) fazem isso.

Instalação e uso: ver `examples/core/plugin/README.md`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa

from dataipsum.contracts.types import LogicalType, string

if TYPE_CHECKING:
    from dataipsum.contracts.generator import GenContext, RowBatch
    from dataipsum.errors import ValidationError
    from dataipsum.schema.models import ColumnSpec
    from dataipsum.seeds import Draws

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PLACA_MAX_LENGTH = 7


class ExemploPlacaGenerator:
    """Gera placas fictícias no formato `ABC1D23`, determinístico por `Draws`."""

    name = "exemplo_placa"
    supports_invalid = False
    supports_format = False
    deterministic = True
    # Slots 0 e 1 são reservados pelo motor (null/invalid, DD-00 §3.6); este
    # gerador usa 6 slots livres, a partir do slot 2.
    draw_slots = 6

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        return []

    def logical_type(self, column: ColumnSpec) -> LogicalType:
        return string(_PLACA_MAX_LENGTH)

    def depends_on(self, column: ColumnSpec) -> list[str]:
        return []

    def implied_columns(self, column: ColumnSpec) -> list[ColumnSpec]:
        return []

    def generate(
        self, column: ColumnSpec, batch: RowBatch, draws: Draws, ctx: GenContext
    ) -> pa.Array:
        letter_indices = np.stack(
            [draws.integers(slot, 0, len(_LETTERS)) for slot in range(2, 5)], axis=1
        )
        digit_1 = draws.integers(5, 0, 10)
        letter_4 = draws.integers(6, 0, len(_LETTERS))
        digit_23 = draws.integers(7, 0, 100)
        placas = [
            f"{_LETTERS[a]}{_LETTERS[b]}{_LETTERS[c]}{d1}{_LETTERS[e]}{d23:02d}"
            for (a, b, c), d1, e, d23 in zip(
                letter_indices.tolist(), digit_1.tolist(), letter_4.tolist(), digit_23.tolist()
            )
        ]
        return pa.array(placas, type=pa.string())
