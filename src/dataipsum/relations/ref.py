"""Gerador `ref` (DD-01 §B.3.3, §B.4).

Implementado como um `Generator` protocol-compliant e sem estado próprio de
schema: para funcionar, o `column` recebido precisa vir "enriquecido" com as
chaves privadas `_dirigente`, `_dirigente_parent_indices`,
`_target_pk_column` e (quando não dirigente) `_target_population` — quem tem
essa informação é um `Planner`, que a injeta antes de chamar `generate`. Isso
mantém `RefGenerator.generate` uma função pura de `(column, batch, draws,
ctx)`, como o contrato `Generator` exige, sem precisar de uma referência
direta a um `Planner` (que não cabe no protocolo `GenContext`).

O caminho usado internamente por `Planner.row_at` não passa por aqui: ele
resolve `ref` diretamente (mais direto, evita montar o dicionário de
enriquecimento a cada chamada). Este módulo existe para (1) registrar `ref`
como tipo de coluna conhecido no registry e (2) ser testável isoladamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from dataipsum import seeds
from dataipsum.contracts.types import LogicalType, int64
from dataipsum.errors import ValidationError
from dataipsum.relations import _zipf, feistel

if TYPE_CHECKING:
    from dataipsum.contracts.generator import GenContext, RowBatch
    from dataipsum.schema.models import ColumnSpec


def _sample_non_dirigente_ranks(
    column: ColumnSpec, draws: seeds.Draws, population: int
) -> NDArray[np.int64]:
    distribution = column.params.get("distribution")
    shuffle = column.params.get("shuffle", True)
    if isinstance(distribution, dict) and isinstance(distribution.get("zipf"), dict):
        s = float(distribution["zipf"]["s"])
        rank0 = _zipf.rank(draws.seed_col, draws.rows, 0, s, population)
    else:
        rank0 = draws.choice(0, population)
    if shuffle:
        key = seeds.derive(draws.seed_col, "shuffle")
        return np.asarray(feistel.perm(rank0, population, key), dtype=np.int64)
    return rank0


@dataclass
class RefGenerator:
    """Gerador do tipo `ref`: o valor é sempre `pk_at(tabela_alvo, j)` (§B.3.3)."""

    name: str = "ref"
    supports_invalid: bool = False
    supports_format: bool = False
    deterministic: bool = True
    draw_slots: int = 2
    _pk_logical_types: dict[str, LogicalType] = field(default_factory=dict, repr=False)

    def bind_pk_logical_types(self, pk_logical_types: dict[str, LogicalType]) -> None:
        self._pk_logical_types = dict(pk_logical_types)

    def validate_params(self, column: ColumnSpec, ctx: object) -> list[ValidationError]:
        if not isinstance(column.params.get("table"), str):
            return [ValidationError(path="table", message="'ref' requer 'params.table' (string)")]
        return []

    def logical_type(self, column: ColumnSpec) -> LogicalType:
        target = column.params.get("table")
        if isinstance(target, str) and target in self._pk_logical_types:
            return self._pk_logical_types[target]
        return int64()

    def depends_on(self, column: ColumnSpec) -> list[str]:
        return []

    def implied_columns(self, column: ColumnSpec) -> list[ColumnSpec]:
        return []

    def generate(
        self,
        column: ColumnSpec,
        batch: RowBatch,
        draws: seeds.Draws,
        ctx: GenContext,
    ) -> pa.Array:
        target_table = str(column.params["table"])
        pk_column = str(column.params["_target_pk_column"])
        if bool(column.params.get("_dirigente", False)):
            parent_indices = np.asarray(column.params["_dirigente_parent_indices"], dtype=np.int64)
        else:
            population = cast(int, column.params["_target_population"])
            parent_indices = _sample_non_dirigente_ranks(column, draws, population)
        parent_values = ctx.parent_rows(target_table, parent_indices, [pk_column])
        return parent_values[pk_column]
