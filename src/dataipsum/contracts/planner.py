"""Contrato `Planner`, `RunPlan` e `ChunkSpec` (DD-00 §3.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from dataipsum.errors import ValidationError

if TYPE_CHECKING:
    from dataipsum.schema.models import ColumnSpec, Schema


@dataclass(frozen=True)
class ParentRef:
    table: str
    first_index: int
    count: int
    first_child_offset: int


@dataclass(frozen=True)
class ChunkSpec:
    id: int
    first_row: int
    rows: int
    parent: ParentRef | None = None


@dataclass(frozen=True)
class TablePlan:
    rows: int
    chunks: tuple[ChunkSpec, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RunPlan:
    """Plano de execução: tabelas em ordem topológica e seus chunks. Serializável em JSON."""

    order: tuple[str, ...]
    tables: dict[str, TablePlan]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "order": list(self.order),
            "tables": {
                name: {
                    "rows": plan.rows,
                    "chunks": [
                        {
                            "id": chunk.id,
                            "first_row": chunk.first_row,
                            "rows": chunk.rows,
                            "parent": None
                            if chunk.parent is None
                            else {
                                "table": chunk.parent.table,
                                "first_index": chunk.parent.first_index,
                                "count": chunk.parent.count,
                                "first_child_offset": chunk.parent.first_child_offset,
                            },
                        }
                        for chunk in plan.chunks
                    ],
                }
                for name, plan in self.tables.items()
            },
        }


class Planner(Protocol):
    """Implementado pela trilha B (DD-01): grafo de relações e derivação de linhas filhas."""

    def validate(self, schema: Schema) -> list[ValidationError]: ...

    def implied_columns(self, table: object) -> list[ColumnSpec]:
        """Colunas acrescentadas no nível da tabela (ex.: colunas de tabelas `thread`)."""
        return []

    def plan(self, schema: Schema, seed: int, chunk_size: int) -> RunPlan: ...

    def pk_at(self, table: str, indices: NDArray[np.int64]) -> pa.Array: ...

    def parent_index_of(self, table: str, chunk: ChunkSpec, batch: object) -> NDArray[np.int64]: ...

    def row_at(
        self, table: str, indices: NDArray[np.int64], columns: list[str]
    ) -> dict[str, pa.Array]: ...

    def parent_index_for_ref(
        self, table: str, column: str, indices: NDArray[np.int64]
    ) -> NDArray[np.int64]:
        """Índice, na tabela alvo da coluna `ref` `column`, de cada linha `indices` de `table`
        (extensão da integração S5, DD-01 §3: usada para montar o contexto de colunas LLM que
        referenciam `{ref.coluna}` do pai, DD-01 §C.3.2)."""
        raise NotImplementedError
