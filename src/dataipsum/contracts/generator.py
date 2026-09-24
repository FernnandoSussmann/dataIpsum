"""Contrato `Generator` e estruturas trocadas com o motor (DD-00 §3.5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from dataipsum.contracts.types import LogicalType
from dataipsum.errors import ValidationError

if TYPE_CHECKING:
    from dataipsum.schema.models import ColumnSpec
    from dataipsum.seeds import Draws


@dataclass(frozen=True)
class RowBatch:
    """Lote de linhas: índices globais (nem sempre contíguos) e máscara de inválidos."""

    rows: NDArray[np.int64]
    invalid_mask: NDArray[np.bool_] | None = None


class GenContext(Protocol):
    """Contexto de geração entregue a um `Generator.generate`."""

    @property
    def locale(self) -> str: ...

    def same_row(self, column_names: list[str]) -> dict[str, pa.Array]:
        """Colunas determinísticas já geradas no mesmo lote."""
        ...

    def parent_rows(
        self, table: str, parent_indices: NDArray[np.int64], columns: list[str]
    ) -> dict[str, pa.Array]:
        """Recálculo local de linhas de outra tabela."""
        ...


class Generator(Protocol):
    """Gerador de valores para um tipo de coluna. Vetorizado: recebe N linhas, devolve N valores."""

    name: str
    supports_invalid: bool
    supports_format: bool
    deterministic: bool
    draw_slots: int

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]: ...

    def logical_type(self, column: ColumnSpec) -> LogicalType: ...

    def depends_on(self, column: ColumnSpec) -> list[str]:
        """Colunas determinísticas da mesma linha das quais este gerador depende. Padrão: []."""
        return []

    def implied_columns(self, column: ColumnSpec) -> list[ColumnSpec]:
        """Colunas acrescentadas ao final da tabela por este tipo. Padrão: []."""
        return []

    def generate(
        self,
        column: ColumnSpec,
        batch: RowBatch,
        draws: Draws,
        ctx: GenContext,
    ) -> pa.Array: ...
