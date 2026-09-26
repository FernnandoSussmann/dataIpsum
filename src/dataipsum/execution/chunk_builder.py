"""Construtor de chunk, executado no worker (DD-01 §D.3.2).

`build_record_batch` monta o `pyarrow.RecordBatch` de um chunk, na ordem fixa da
especificação: PK, refs (dirigente e não dirigente, via `Planner.row_at`), implícitas
determinísticas de thread, demais geradores em ordem topológica de `depends_on`, máscara de
nulos, colunas LLM (`llm_*` e o `texto`/`is_offensive`/`is_placeholder` de tabelas thread, via
`dataipsum.llm.filler`/`dataipsum.llm.threads`) e flags implícitas ao fim. `build_chunk`
empacota esse batch num `ChunkResult`, escrevendo no `sink` quando um é fornecido — e só quando
o conteúdo é seguro para persistir (§C.3.5, §C.3.7: um chunk com coluna LLM pendente por falha de
provedor ou por toxicidade esgotada, sem `on_failure: placeholder`, nunca é gravado).

Decisão de integração (S5, DD-01 §0 e §C.4): o formato de `chunk_ctx`/`RowContext` que a trilha C
espera (`dataipsum.llm.filler.RowContext`: `row`, `same_row`, `parent_rows` já resolvidos) é
montado aqui a partir do `Planner` (trilha B), em vez de mudar a API pública de C. Isso também
exigiu uma pequena extensão do `Planner` (`parent_index_for_ref`, DD-01 §S5): `row_at`/`pk_at` só
devolvem o *valor* de PK do pai, nunca o índice, e colunas LLM que referenciam `{ref.coluna}`
(§C.3.2) precisam do índice para recalcular outras colunas do pai.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from dataipsum import seeds as seeds_module
from dataipsum.contracts.executor import ChunkResult, ChunkResultFlags
from dataipsum.contracts.generator import RowBatch
from dataipsum.errors import SchemaError, ValidationError
from dataipsum.execution.llm_engine import build_llm_engine
from dataipsum.llm import filler as llm_filler
from dataipsum.llm import threads as llm_threads
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
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from dataipsum.contracts.executor import ChunkStatus, ChunkTask
    from dataipsum.contracts.generator import GenContext, Generator
    from dataipsum.contracts.planner import ChunkSpec, Planner
    from dataipsum.contracts.sink import Sink
    from dataipsum.llm.filler import FillOutcome, LLMEngine, RowContext
    from dataipsum.registry import Registry
    from dataipsum.schema.models import ColumnSpec, Schema, TableSpec


def _instantiate_generator(registry: Registry, type_name: str) -> Generator:
    generator_cls = cast("type[Generator]", registry.get_generator(type_name))
    return generator_cls()


def _table_spec(schema: Schema, table_name: str) -> TableSpec:
    return next(table for table in schema.tables if table.name == table_name)


def _row_indices(chunk: ChunkSpec) -> NDArray[np.int64]:
    return np.arange(chunk.first_row, chunk.first_row + chunk.rows, dtype=np.int64)


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


def _null_mask_array(
    array: pa.Array, column: ColumnSpec, chunk_seed: int, row_indices: NDArray[np.int64]
) -> pa.Array:
    if column.null_ratio <= 0:
        return array
    null_mask = uniform(chunk_seed, row_indices, NULL_SLOT) < column.null_ratio
    return pc.if_else(pa.array(null_mask), pa.nulls(len(array), type=array.type), array)


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
    return _null_mask_array(array, column, chunk_seed, row_indices)


def _table_by_name(schema: Schema, name: str) -> TableSpec:
    return next(table for table in schema.tables if table.name == name)


def _deterministic_target_columns(target_table: TableSpec) -> list[str]:
    """Colunas de `target_table` seguras para entrar num prompt LLM (§C.3.2): nem chave
    primária, nem `ref` (evita expor valores de chave por um caminho indireto), nem `llm_*`
    (o pai só empresta colunas determinísticas, §C.4)."""
    pk_columns = frozenset(target_table.primary_key.columns)
    return [
        column.name
        for column in target_table.columns
        if column.name not in pk_columns and column.type != "ref" and not column.is_llm
    ]


def _build_row_contexts(
    schema: Schema,
    table: TableSpec,
    row_indices: NDArray[np.int64],
    arrays: dict[str, pa.Array],
    planner: Planner,
) -> list[RowContext]:
    pk_columns = frozenset(table.primary_key.columns)
    same_row_names = [name for name in arrays if name not in pk_columns]

    parent_columns_by_ref: dict[str, dict[str, pa.Array]] = {}
    for column in table.columns:
        if column.type != "ref":
            continue
        target_name = str(column.params["table"])
        target_table = _table_by_name(schema, target_name)
        target_columns = _deterministic_target_columns(target_table)
        if not target_columns:
            continue
        parent_indices = planner.parent_index_for_ref(table.name, column.name, row_indices)
        parent_columns_by_ref[column.name] = planner.row_at(
            target_name, parent_indices, target_columns
        )

    contexts: list[RowContext] = []
    for position, global_row in enumerate(row_indices.tolist()):
        same_row = {name: arrays[name][position].as_py() for name in same_row_names}
        parent_rows = {
            ref_name: {col: values[position].as_py() for col, values in columns.items()}
            for ref_name, columns in parent_columns_by_ref.items()
        }
        contexts.append(
            llm_filler.RowContext(row=int(global_row), same_row=same_row, parent_rows=parent_rows)
        )
    return contexts


def _outcome_should_write(status: str, is_placeholder: Sequence[bool]) -> bool:
    """§C.3.5/§C.3.7: um chunk LLM `pending` fica sem gravar; um chunk `pending` só por
    `on_failure: placeholder` é gravado com o texto lorem (todas as linhas marcadas)."""
    if status == "done":
        return True
    return len(is_placeholder) > 0 and all(is_placeholder)


def _merge_flags(a: ChunkResultFlags, b: ChunkResultFlags) -> ChunkResultFlags:
    return ChunkResultFlags(
        placeholders=a.placeholders + b.placeholders,
        offensive=a.offensive + b.offensive,
        toxicity_exhausted=a.toxicity_exhausted + b.toxicity_exhausted,
        thread_fallbacks=a.thread_fallbacks + b.thread_fallbacks,
    )


def _fill_llm_column(
    engine: LLMEngine,
    schema: Schema,
    table: TableSpec,
    column: ColumnSpec,
    contexts: list[RowContext],
    root_seed: int,
) -> FillOutcome:
    default_provider = schema.llm.default_provider if schema.llm is not None else ""
    config = llm_filler.column_llm_config(column, default_provider=default_provider)
    if config.mode == "pool":
        pool = llm_filler.PoolBuilder(engine).build(schema, table, column, root_seed=root_seed)
        return llm_filler.fill_pool_column(
            pool, schema, table, column, contexts, root_seed=root_seed
        )
    return llm_filler.fill_unique_column(
        engine, schema, table, column, contexts, root_seed=root_seed
    )


def _author_labels(
    planner: Planner,
    participants_table: TableSpec | None,
    label_column: str | None,
    pk_values: list[object],
) -> list[str]:
    """Rótulo do autor de cada mensagem (§C.3.8, "rótulos dos participantes via
    `participants.label_column`"). Só inverte PK -> índice para a estratégia `sequence`
    (O(1), DD-01 §B.3.1); nas demais, usa o valor da PK como rótulo — o `Planner` não expõe
    (nem deveria: §C.3.2 proíbe chave em prompt) uma inversão genérica de PK para índice, e as
    demais estratégias não são O(1) invertíveis sem ela."""
    if participants_table is None or not label_column:
        return [str(value) for value in pk_values]
    pk_spec = participants_table.primary_key
    if pk_spec.strategy != "sequence":
        return [str(value) for value in pk_values]
    start = pk_spec.start if pk_spec.start is not None else 1
    step = pk_spec.step if pk_spec.step is not None else 1
    indices = np.array(
        [(cast("int", value) - start) // step for value in pk_values], dtype=np.int64
    )
    values = planner.row_at(participants_table.name, indices, [label_column])[label_column]
    return [str(value) for value in values.to_pylist()]


def _fill_thread_columns(
    engine: LLMEngine,
    schema: Schema,
    table: TableSpec,
    row_indices: NDArray[np.int64],
    arrays: dict[str, pa.Array],
    planner: Planner,
    root_seed: int,
) -> tuple[dict[str, pa.Array], bool, bool, ChunkResultFlags]:
    """Preenche `texto`/`is_offensive`/`is_placeholder` de uma tabela `thread` (§C.3.8): uma
    chamada por thread (agrupando as linhas do chunk pela sua thread), nunca por linha."""
    assert table.rows_from is not None
    via_name = table.rows_from.via
    via_column = next(column for column in table.columns if column.name == via_name)
    subject_table_name = str(via_column.params["table"])
    subject_table = _table_by_name(schema, subject_table_name)
    subject_columns = _deterministic_target_columns(subject_table)

    thread_block = table.thread or {}
    participants = thread_block.get("participants", {})
    participants_table_name = participants.get("table") if isinstance(participants, dict) else None
    label_column = (
        participants.get("label_column") if isinstance(participants, dict) else None
    ) or None
    participants_table = (
        _table_by_name(schema, str(participants_table_name))
        if isinstance(participants_table_name, str)
        else None
    )

    default_provider = schema.llm.default_provider if schema.llm is not None else ""
    config = llm_threads.thread_llm_config(thread_block, default_provider=default_provider)

    group_ids = planner.parent_index_for_ref(table.name, via_name, row_indices).tolist()
    seq_values = arrays["seq"].to_pylist()
    autor_values = arrays["autor"].to_pylist()

    groups: dict[int, list[int]] = {}
    for position, group_id in enumerate(group_ids):
        groups.setdefault(int(group_id), []).append(position)

    texts: list[str | None] = [None] * len(row_indices)
    offensive: list[bool] = [False] * len(row_indices)
    placeholder: list[bool] = [False] * len(row_indices)
    pending = False
    should_write = True
    flags = ChunkResultFlags()
    text_col_seed = seed_column(seed_table(root_seed, table.name), "texto")

    for group_id, positions in groups.items():
        ordered_positions = sorted(positions, key=lambda position: seq_values[position])
        subject_row = (
            planner.row_at(
                subject_table_name, np.array([group_id], dtype=np.int64), subject_columns
            )
            if subject_columns
            else {}
        )
        subject_context = {name: values[0].as_py() for name, values in subject_row.items()}
        labels = _author_labels(
            planner, participants_table, label_column, [autor_values[p] for p in ordered_positions]
        )
        messages = [
            llm_threads.ThreadMessage(seq=int(seq_values[position]), autor_label=label)
            for position, label in zip(ordered_positions, labels, strict=True)
        ]
        thread_seed = seeds_module.seed_llm(text_col_seed, group_id)
        outcome = llm_threads.ThreadFiller(engine).fill(
            config,
            thread_seed=thread_seed,
            subject_context=subject_context,
            messages=messages,
            via_column=via_name,
        )
        if outcome.used_fallback:
            flags = _merge_flags(flags, ChunkResultFlags(thread_fallbacks=1))
        if outcome.status != "done":
            pending = True
        group_should_write = _outcome_should_write(outcome.status, outcome.is_placeholder)
        if not group_should_write:
            should_write = False
            continue
        for index, position in enumerate(ordered_positions):
            texts[position] = outcome.texts[index]
            offensive[position] = outcome.is_offensive[index]
            placeholder[position] = outcome.is_placeholder[index]

    result: dict[str, pa.Array] = {}
    if should_write:
        result = {
            "texto": pa.array(texts, type=pa.string()),
            "is_offensive": pa.array(offensive, type=pa.bool_()),
            "is_placeholder": pa.array(placeholder, type=pa.bool_()),
        }
    return result, pending, should_write, flags


def build_record_batch(
    task: ChunkTask, *, planner: Planner, registry: Registry, llm_engine: LLMEngine | None = None
) -> tuple[pa.RecordBatch, ChunkResultFlags, bool, bool]:
    """Monta o `RecordBatch` de um chunk. Devolve também as flags agregadas, se há colunas LLM
    ainda não preenchidas (⇒ o chamador marca `pending_llm`) e se o conteúdo é seguro para
    gravar no sink (`False` só quando alguma coluna LLM ficou pendente por um motivo que não é
    `on_failure: placeholder`, §C.3.5/§C.3.7)."""
    schema = task.schema
    table = _table_spec(schema, task.table)
    chunk = task.chunk_spec
    row_indices = _row_indices(chunk)
    table_seed = seed_table(task.root_seed, task.table)

    pk_names = list(table.primary_key.columns)
    if len(pk_names) == 1:
        arrays: dict[str, pa.Array] = {pk_names[0]: planner.pk_at(task.table, row_indices)}
    else:
        # Chave composta (`many_to_many`, DD-01 §B.3.5): `pk_at` devolve um `StructArray` com
        # um campo por coluna da chave — decompõe em colunas próprias, não a mesma struct
        # repetida sob cada nome.
        pk_struct = planner.pk_at(task.table, row_indices)
        arrays = {name: pk_struct.field(name) for name in pk_names}

    # As colunas implícitas de thread (`seq`, `autor`, `timestamp`, `texto`, `is_offensive`,
    # `is_placeholder`, DD-01 §B.3.6) já estão em `table.columns` a esta altura: quem monta o
    # `ChunkTask` normaliza o schema antes de planejar/gerar (integração S5, ver
    # `dataipsum.execution.orchestrator.normalize_schema_for_generation`).
    is_thread = table.rows_from is not None and table.rows_from.relation == "thread"
    thread_output_names = (
        frozenset({"seq", "autor", "timestamp", "texto", "is_offensive", "is_placeholder"})
        if is_thread
        else frozenset()
    )
    thread_det_names = [
        name
        for name in ("seq", "timestamp")
        if is_thread and any(column.name == name for column in table.columns)
    ]

    ref_names = [
        column.name
        for column in table.columns
        if column.type == "ref" and column.name not in arrays
    ]
    row_at_names = [*ref_names, *thread_det_names]
    if row_at_names:
        arrays.update(planner.row_at(task.table, row_indices, row_at_names))
        columns_by_name_for_null = {column.name: column for column in table.columns}
        for name in ref_names:
            column = columns_by_name_for_null[name]
            if column.null_ratio > 0:
                chunk_seed = seed_chunk(seed_column(table_seed, name), chunk.id)
                arrays[name] = _null_mask_array(arrays[name], column, chunk_seed, row_indices)

    remaining = [
        column
        for column in table.columns
        if column.name not in arrays
        and column.name not in thread_output_names
        and not column.is_llm
    ]
    ordered_names = _dependency_order(remaining, registry)
    columns_by_name = {column.name: column for column in table.columns}

    locale = table.locale or schema.locale
    ctx = _WorkerContext(locale, planner, arrays)

    for name in ordered_names:
        column = columns_by_name[name]
        generator = _instantiate_generator(registry, column.type)
        col_seed = seed_column(table_seed, name)
        chunk_seed = seed_chunk(col_seed, chunk.id)
        arrays[name] = _apply_invalid_and_null(generator, column, chunk_seed, row_indices, ctx)

    all_llm_columns = [column for column in table.columns if column.is_llm]
    llm_implied = [column for column in all_llm_columns if column.name in thread_output_names]
    llm_columns = [column for column in all_llm_columns if column not in llm_implied]
    flags = ChunkResultFlags()
    llm_pending = False
    should_write = True

    if llm_columns or llm_implied:
        engine = llm_engine if llm_engine is not None else build_llm_engine(schema, registry)
        if engine is None:
            raise SchemaError(
                [
                    ValidationError(
                        path=f"{table.name}",
                        message="schema tem coluna 'llm_*', mas não define a seção 'llm'",
                    )
                ]
            )
        if llm_columns:
            contexts = _build_row_contexts(schema, table, row_indices, arrays, planner)
            for column in llm_columns:
                outcome = _fill_llm_column(engine, schema, table, column, contexts, task.root_seed)
                flags = _merge_flags(flags, outcome.flags)
                if outcome.status != "done":
                    llm_pending = True
                if _outcome_should_write(outcome.status, outcome.is_placeholder):
                    arrays[column.name] = pa.array(outcome.texts, type=pa.string())
                else:
                    should_write = False
        if llm_implied:
            thread_arrays, pending, wrote, thread_flags = _fill_thread_columns(
                engine, schema, table, row_indices, arrays, planner, task.root_seed
            )
            arrays.update(thread_arrays)
            flags = _merge_flags(flags, thread_flags)
            llm_pending = llm_pending or pending
            should_write = should_write and wrote

    ordered_column_names = [column.name for column in table.columns]
    for name in ordered_column_names:
        if name not in arrays:
            arrays[name] = pa.nulls(chunk.rows)

    batch = pa.RecordBatch.from_arrays(
        [arrays[name] for name in ordered_column_names], names=ordered_column_names
    )
    return batch, flags, llm_pending, should_write


def build_chunk(
    task: ChunkTask,
    *,
    planner: Planner,
    registry: Registry,
    sink: Sink | None = None,
    llm_engine: LLMEngine | None = None,
) -> ChunkResult:
    """Constrói o chunk e, se `sink` for fornecido, escreve nele (§D.3.2: "a escrita acontece no
    worker") — desde que o conteúdo seja seguro para persistir (`should_write`). Sem `sink`, só
    constrói e conta as linhas — usado pelos testes que precisam inspecionar o `RecordBatch`
    diretamente via `build_record_batch`."""
    batch, flags, llm_pending, should_write = build_record_batch(
        task, planner=planner, registry=registry, llm_engine=llm_engine
    )
    sink_ref = None
    sha256 = None
    if sink is not None and should_write:
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
