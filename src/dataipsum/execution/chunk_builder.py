"""Construtor de chunk, executado no worker (DD-01 §D.3.2).

`build_record_batch` monta o `pyarrow.RecordBatch` de um chunk, na ordem fixa da
especificação: PK, refs, implícitas determinísticas de thread, demais geradores em
ordem topológica de `depends_on`, máscara de nulos, colunas LLM (ainda não
implementadas — trilha C) e flags implícitas ao fim. `build_chunk` empacota esse
batch num `ChunkResult`, escrevendo no `sink` quando um é fornecido.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from dataipsum.contracts.executor import ChunkResult, ChunkResultFlags
from dataipsum.contracts.generator import RowBatch
from dataipsum.errors import SchemaError, ValidationError
from dataipsum.seeds import (
    INVALID_SLOT,
    NULL_SLOT,
    Draws,
    seed_chunk,
    seed_column,
    seed_table,
    uniform,
)

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from dataipsum.contracts.executor import ChunkStatus, ChunkTask
    from dataipsum.contracts.generator import GenContext, Generator
    from dataipsum.contracts.planner import ChunkSpec, Planner
    from dataipsum.contracts.sink import Sink
    from dataipsum.registry import Registry
    from dataipsum.schema.models import ColumnSpec, Schema, TableSpec


def _instantiate_generator(registry: Registry, type_name: str) -> Generator:
    generator_cls = cast("type[Generator]", registry.get_generator(type_name))
    return generator_cls()


def _table_spec(schema: Schema, table_name: str) -> TableSpec:
    return next(table for table in schema.tables if table.name == table_name)


def _row_indices(chunk: ChunkSpec) -> NDArray[np.int64]:
    return np.arange(chunk.first_row, chunk.first_row + chunk.rows, dtype=np.int64)


def _parent_indices(chunk: ChunkSpec) -> NDArray[np.int64]:
    """Índices, na tabela pai, de cada linha do chunk filho, a partir de
    `ChunkSpec.parent` (`first_index`, `count`, `first_child_offset`)."""
    parent = chunk.parent
    if parent is None:  # pragma: no cover -- guardado pelo chamador
        raise SchemaError([ValidationError(path="chunk.parent", message="chunk sem pai")])
    child_positions = np.arange(chunk.rows, dtype=np.int64) + parent.first_child_offset
    return parent.first_index + (child_positions % parent.count)


def _dependency_order(columns: list[ColumnSpec], registry: Registry) -> list[str]:
    graph: dict[str, list[str]] = {}
    for column in columns:
        deps = (
            _instantiate_generator(registry, column.type).depends_on(column)
            if column.type in registry.generators
            else []
        )
        graph[column.name] = deps

    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise SchemaError(
                [ValidationError(path=f"columns.{name}", message="ciclo de dependências")]
            )
        visiting.add(name)
        for dep in graph.get(name, []):
            if dep in graph:
                visit(dep)
        visiting.discard(name)
        visited.add(name)
        order.append(name)

    for column in columns:
        visit(column.name)
    return order


class _WorkerContext:
    """`GenContext` do worker: colunas já geradas no chunk e recálculo de linhas pai."""

    def __init__(self, locale: str, planner: Planner, arrays: dict[str, pa.Array]) -> None:
        self._locale = locale
        self._planner = planner
        self._arrays = arrays

    @property
    def locale(self) -> str:
        return self._locale

    def same_row(self, column_names: list[str]) -> dict[str, pa.Array]:
        return {name: self._arrays[name] for name in column_names}

    def parent_rows(
        self, table: str, parent_indices: NDArray[np.int64], columns: list[str]
    ) -> dict[str, pa.Array]:
        return self._planner.row_at(table, parent_indices, columns)


def _apply_invalid_and_null(
    generator: Generator,
    column: ColumnSpec,
    chunk_seed: int,
    row_indices: NDArray[np.int64],
    ctx: GenContext,
) -> pa.Array:
    invalid_mask = (
        uniform(chunk_seed, row_indices, INVALID_SLOT) < column.invalid_ratio
        if column.invalid_ratio > 0 and generator.supports_invalid
        else None
    )
    batch = RowBatch(rows=row_indices, invalid_mask=invalid_mask)
    draws = Draws(seed_col=chunk_seed, rows=row_indices)
    array = generator.generate(column, batch, draws, ctx)
    if column.null_ratio > 0:
        null_mask = uniform(chunk_seed, row_indices, NULL_SLOT) < column.null_ratio
        array = pc.if_else(pa.array(null_mask), pa.nulls(len(array), type=array.type), array)
    return array


def build_record_batch(
    task: ChunkTask, *, planner: Planner, registry: Registry
) -> tuple[pa.RecordBatch, ChunkResultFlags, bool]:
    """Monta o `RecordBatch` de um chunk. Devolve também as flags e se há
    colunas LLM ainda não preenchidas (⇒ o chamador marca `pending_llm`)."""
    schema = task.schema
    table = _table_spec(schema, task.table)
    chunk = task.chunk_spec
    row_indices = _row_indices(chunk)
    table_seed = seed_table(task.root_seed, task.table)

    pk_names = frozenset(table.primary_key.columns)
    arrays: dict[str, pa.Array] = {
        name: planner.pk_at(task.table, row_indices) for name in pk_names
    }

    via_name = table.rows_from.via if table.rows_from is not None else None
    if chunk.parent is not None and via_name is not None and via_name not in arrays:
        arrays[via_name] = planner.pk_at(chunk.parent.table, _parent_indices(chunk))

    implied_columns = (
        planner.implied_columns(table)
        if table.rows_from is not None and table.rows_from.relation == "thread"
        else []
    )
    implied_names = [column.name for column in implied_columns]

    remaining = [
        column
        for column in table.columns
        if column.name not in arrays and column.name not in implied_names and not column.is_llm
    ]
    ordered_names = _dependency_order(remaining, registry)
    columns_by_name = {column.name: column for column in [*table.columns, *implied_columns]}

    locale = table.locale or schema.locale
    ctx = _WorkerContext(locale, planner, arrays)

    llm_pending = False
    for name in [*implied_names, *ordered_names]:
        column = columns_by_name.get(name)
        if column is None:
            continue
        generator = _instantiate_generator(registry, column.type)
        col_seed = seed_column(table_seed, name)
        chunk_seed = seed_chunk(col_seed, chunk.id)
        arrays[name] = _apply_invalid_and_null(generator, column, chunk_seed, row_indices, ctx)

    for column in table.columns:
        if column.is_llm and column.name not in arrays:
            arrays[column.name] = pa.nulls(chunk.rows)
            llm_pending = True

    ordered_column_names = [column.name for column in table.columns] + implied_names
    batch = pa.RecordBatch.from_arrays(
        [arrays[name] for name in ordered_column_names], names=ordered_column_names
    )
    return batch, ChunkResultFlags(), llm_pending


def build_chunk(
    task: ChunkTask, *, planner: Planner, registry: Registry, sink: Sink | None = None
) -> ChunkResult:
    """Constrói o chunk e, se `sink` for fornecido, escreve nele (§D.3.2: "a
    escrita acontece no worker"). Sem `sink`, só constrói e conta as linhas —
    usado pelos testes que precisam inspecionar o `RecordBatch` diretamente
    via `build_record_batch`."""
    batch, flags, llm_pending = build_record_batch(task, planner=planner, registry=registry)
    sink_ref = None
    sha256 = None
    if sink is not None:
        receipt = sink.write_chunk(task.chunk_spec.id, batch)
        sink_ref = receipt.sink_ref
        sha256 = receipt.sha256
    status: ChunkStatus = "pending_llm" if llm_pending else "done"
    return ChunkResult(
        table=task.table,
        chunk_id=task.chunk_spec.id,
        status=status,
        rows=task.chunk_spec.rows,
        sink_ref=sink_ref,
        sha256=sha256,
        flags=flags,
    )
