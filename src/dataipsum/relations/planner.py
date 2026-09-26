"""`RelationsPlanner`: implementação do `Planner` (DD-00 §3.5) pela trilha B.

Chaves, relações (1:1, 1:N, N:N, thread), cardinalidade e recálculo local
(`pk_at`/`row_at`), sem consultar dados já gerados (DD-01 §B).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

from dataipsum import seeds
from dataipsum.contracts.generator import RowBatch
from dataipsum.contracts.planner import ChunkSpec, ParentRef, RunPlan, TablePlan
from dataipsum.errors import PlanError, ResourceLimitError, ValidationError
from dataipsum.relations import _zipf, cardinality, feistel, graph, keys

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dataipsum.contracts.generator import Generator
    from dataipsum.schema.models import ColumnSpec, Schema, TableSpec

RESERVED_THREAD_COLUMNS = ("seq", "autor", "timestamp", "texto", "is_offensive", "is_placeholder")
_THREAD_DETERMINISTIC_COLUMNS = ("seq", "autor", "timestamp")
_MAX_ROW_CACHE_CHUNKS = 64
_LRU_CHUNK_SIZE = 4096


@dataclass(frozen=True)
class _RootInfo:
    pass


@dataclass(frozen=True)
class _OneToOneInfo:
    parent_table: str
    via_column: str
    coverage: float
    perm_key: int
    parent_rows: int


@dataclass(frozen=True)
class _OneToManyInfo:
    parent_table: str
    via_column: str
    card_spec: cardinality.CardinalitySpec
    cumulative: NDArray[np.int64]


@dataclass(frozen=True)
class _ManyToManyInfo:
    parent_table: str
    via_column: str
    pair_table: str
    pair_column: str
    card_spec: cardinality.CardinalitySpec
    cumulative: NDArray[np.int64]
    pair_key_base: int


@dataclass(frozen=True)
class _ThreadParticipants:
    table: str
    count: int
    label_column: str


@dataclass(frozen=True)
class _ThreadInfo(_OneToManyInfo):
    participants: _ThreadParticipants
    start_min_epoch: int = 0
    start_max_epoch: int = 0
    gap_min_seconds: int = 1
    gap_max_seconds: int = 1
    participants_key_base: int = 0
    author_key_base: int = 0
    timestamp_key_base: int = 0


RelationInfo = _RootInfo | _OneToOneInfo | _OneToManyInfo | _ManyToManyInfo | _ThreadInfo


@dataclass(frozen=True)
class _TableState:
    spec: TableSpec
    relation_info: RelationInfo
    rows: int
    pk_column: str
    pk_strategy: Literal["sequence", "seeded_int", "seeded_uuid", "composite"]
    pk_start: int
    pk_step: int
    table_seed: int
    columns_by_name: dict[str, ColumnSpec]


def _find_column(table: TableSpec, name: str) -> ColumnSpec | None:
    return next((column for column in table.columns if column.name == name), None)


def _iso_to_epoch_seconds(value: object) -> int:
    return int(datetime.fromisoformat(str(value)).timestamp())


def _relation_error(table_name: str, message: str) -> ValidationError:
    return ValidationError(path=f"tables[?({table_name})].rows_from", message=message)


def _validate_reserved_thread_names(table: TableSpec) -> list[ValidationError]:
    if table.rows_from is None or table.rows_from.relation != "thread":
        return []
    declared = {column.name for column in table.columns}
    collisions = sorted(declared & set(RESERVED_THREAD_COLUMNS))
    return [
        ValidationError(
            path=f"tables[?({table.name})].columns",
            message=f"nome de coluna reservado em tabela thread: '{name}'",
        )
        for name in collisions
    ]


def _validate_ref_columns(table: TableSpec, table_names: set[str]) -> list[ValidationError]:
    errors = []
    for column in table.columns:
        if column.type != "ref":
            continue
        target = column.params.get("table")
        if not isinstance(target, str) or target not in table_names:
            errors.append(
                ValidationError(
                    path=f"tables[?({table.name})].columns[{column.name}].params.table",
                    message=f"'ref' aponta para tabela inexistente: {target!r}",
                )
            )
    return errors


def _validate_cardinality_shape(
    table: TableSpec, *, max_allowed: int
) -> tuple[cardinality.CardinalitySpec | None, list[ValidationError]]:
    rows_from = table.rows_from
    assert rows_from is not None
    try:
        spec = _cardinality_spec_from_schema(rows_from, max_allowed=max_allowed)
    except ValueError as exc:
        return None, [_relation_error(table.name, str(exc))]
    return spec, []


def _cardinality_spec_from_schema(
    rows_from: object, *, max_allowed: int
) -> cardinality.CardinalitySpec:
    raw_cardinality = rows_from.cardinality  # type: ignore[attr-defined]
    if raw_cardinality is None:
        raise ValueError("relação exige 'rows_from.cardinality'")
    raw_range = raw_cardinality.range
    distribution = raw_cardinality.distribution
    zipf = distribution.zipf if distribution is not None else None
    if zipf is not None:
        if raw_range is None:
            raise ValueError("cardinalidade 'zipf' exige 'range' (min, max)")
        spec: cardinality.CardinalitySpec = cardinality.ZipfCardinality(
            s=zipf.s, min=raw_range.min, max=raw_range.max
        )
    else:
        if raw_range is None:
            raise ValueError("cardinalidade requer 'range' (min, max)")
        spec = cardinality.RangeCardinality(min=raw_range.min, max=raw_range.max)
    if cardinality.max_allowed_for(spec) > max_allowed:
        raise ValueError(f"cardinalidade excede o máximo permitido de {max_allowed}")
    return spec


@dataclass
class RelationsPlanner:
    """`Planner` (DD-00 §3.5) da trilha B. `generators` é usado só para colunas
    comuns (não PK, não `ref`, não implícitas de thread) em `row_at`; a trilha
    B usa geradores fake para isso (DD-01 §0)."""

    generators: Mapping[str, Generator] = field(default_factory=dict)
    _schema: Schema | None = field(default=None, init=False, repr=False)
    _seed: int | None = field(default=None, init=False, repr=False)
    _chunk_size: int | None = field(default=None, init=False, repr=False)
    _order: tuple[str, ...] = field(default_factory=tuple, init=False, repr=False)
    _tables: dict[str, _TableState] = field(default_factory=dict, init=False, repr=False)
    _run_plan: RunPlan | None = field(default=None, init=False, repr=False)
    _row_cache: OrderedDict[tuple[str, str, int], dict[str, pa.Array]] = field(
        default_factory=OrderedDict, init=False, repr=False
    )

    # ------------------------------------------------------------------ validate

    def validate(self, schema: Schema) -> list[ValidationError]:
        table_names = {table.name for table in schema.tables}
        errors: list[ValidationError] = []
        try:
            graph.topological_order(schema)
        except PlanError as exc:
            errors.append(ValidationError(path="tables", message=str(exc)))

        for table in schema.tables:
            errors.extend(_validate_reserved_thread_names(table))
            errors.extend(_validate_ref_columns(table, table_names))
            errors.extend(self._validate_table_relation(table, table_names))
        return errors

    def _validate_table_relation(
        self, table: TableSpec, table_names: set[str]
    ) -> list[ValidationError]:
        rows_from = table.rows_from
        if rows_from is None:
            return []
        errors: list[ValidationError] = []
        via_column = _find_column(table, rows_from.via)
        if via_column is None or via_column.type != "ref":
            errors.append(
                _relation_error(
                    table.name,
                    f"'via' ('{rows_from.via}') precisa ser uma coluna 'ref' da própria tabela",
                )
            )
            return errors
        target = via_column.params.get("table")
        if not isinstance(target, str) or target not in table_names:
            return errors  # já relatado por _validate_ref_columns

        if rows_from.relation == "one_to_one":
            if rows_from.cardinality is not None:
                errors.append(
                    _relation_error(table.name, "'cardinality' não é válido em 'one_to_one'")
                )
            coverage = rows_from.coverage if rows_from.coverage is not None else 1.0
            if not (0.0 < coverage <= 1.0):
                errors.append(_relation_error(table.name, "'coverage' precisa estar em (0, 1]"))
            return errors

        if rows_from.coverage is not None:
            errors.append(
                _relation_error(table.name, f"'coverage' não é válido em '{rows_from.relation}'")
            )

        if rows_from.relation == "many_to_many":
            if not isinstance(rows_from.pair, str):
                errors.append(_relation_error(table.name, "'many_to_many' exige 'pair'"))
            elif table.primary_key.strategy != "composite":
                errors.append(
                    _relation_error(
                        table.name, "'many_to_many' exige 'primary_key.strategy: composite'"
                    )
                )
            max_allowed = cardinality.MAX_CARDINALITY
        elif rows_from.relation == "thread":
            max_allowed = cardinality.MAX_THREAD_CARDINALITY
        else:
            max_allowed = cardinality.MAX_CARDINALITY

        _, cardinality_errors = _validate_cardinality_shape(table, max_allowed=max_allowed)
        errors.extend(cardinality_errors)
        return errors

    # --------------------------------------------------------------- implied

    def implied_columns(self, table: object) -> list[ColumnSpec]:
        from dataipsum.schema.models import ColumnSpec

        rows_from = getattr(table, "rows_from", None)
        thread = getattr(table, "thread", None)
        is_thread = rows_from is not None and getattr(rows_from, "relation", None) == "thread"
        if not is_thread or not isinstance(thread, dict):
            return []
        participants = thread.get("participants", {})
        participants_table = participants.get("table") if isinstance(participants, dict) else None
        llm = thread.get("llm", {})
        max_length = llm.get("max_length") if isinstance(llm, dict) else None
        return [
            ColumnSpec(name="seq", type="int32", null_ratio=0.0),
            ColumnSpec(
                name="autor",
                type="ref",
                params={"table": participants_table} if isinstance(participants_table, str) else {},
                null_ratio=0.0,
            ),
            ColumnSpec(name="timestamp", type="timestamp", null_ratio=0.0),
            ColumnSpec(
                name="texto",
                type="llm_conversa",
                max_length=max_length if isinstance(max_length, int) else None,
                null_ratio=0.0,
            ),
            ColumnSpec(name="is_offensive", type="boolean", null_ratio=0.0),
            ColumnSpec(name="is_placeholder", type="boolean", null_ratio=0.0),
        ]

    # ------------------------------------------------------------------- plan

    def plan(self, schema: Schema, seed: int, chunk_size: int) -> RunPlan:
        order = graph.topological_order(schema)
        tables_by_name = {table.name: table for table in schema.tables}
        table_states: dict[str, _TableState] = {}
        table_plans: dict[str, TablePlan] = {}

        for table_name in order:
            table = tables_by_name[table_name]
            state, chunks = self._plan_table(table, table_states, seed, chunk_size)
            table_states[table_name] = state
            table_plans[table_name] = TablePlan(rows=state.rows, chunks=chunks)

        total_rows = sum(plan.rows for plan in table_plans.values())
        if total_rows > schema.limits.max_rows_total:
            raise ResourceLimitError(
                f"total de linhas ({total_rows}) excede 'limits.max_rows_total' "
                f"({schema.limits.max_rows_total})"
            )

        self._schema = schema
        self._seed = seed
        self._chunk_size = chunk_size
        self._order = order
        self._tables = table_states
        self._row_cache.clear()
        self._run_plan = RunPlan(order=order, tables=table_plans)
        return self._run_plan

    def _plan_table(
        self,
        table: TableSpec,
        table_states: dict[str, _TableState],
        root_seed: int,
        chunk_size: int,
    ) -> tuple[_TableState, tuple[ChunkSpec, ...]]:
        table_seed = seeds.seed_table(root_seed, table.name)
        pk_column = table.primary_key.columns[0]

        if table.rows_from is None:
            rows = table.rows or 0
            self._check_sequence_overflow(table, rows)
            state = _TableState(
                spec=table,
                relation_info=_RootInfo(),
                rows=rows,
                pk_column=pk_column,
                pk_strategy=table.primary_key.strategy,
                pk_start=table.primary_key.start or 1,
                pk_step=table.primary_key.step or 1,
                table_seed=table_seed,
                columns_by_name={column.name: column for column in table.columns},
            )
            return state, _simple_chunks(rows, chunk_size)

        rows_from = table.rows_from
        via_column = _find_column(table, rows_from.via)
        if via_column is None or via_column.type != "ref":
            raise PlanError(f"'{table.name}.rows_from.via' precisa ser uma coluna 'ref'")
        parent_table = str(via_column.params["table"])
        parent_state = table_states.get(parent_table)
        if parent_state is None:
            raise PlanError(
                f"tabela pai '{parent_table}' de '{table.name}' não foi planejada ainda"
            )

        if rows_from.relation == "one_to_one":
            coverage = rows_from.coverage if rows_from.coverage is not None else 1.0
            rows = round(coverage * parent_state.rows)
            perm_key = seeds.derive(seeds.seed_relation(table_seed, "relation"), "1:1")
            info: RelationInfo = _OneToOneInfo(
                parent_table=parent_table,
                via_column=via_column.name,
                coverage=coverage,
                perm_key=perm_key,
                parent_rows=parent_state.rows,
            )
            self._check_sequence_overflow(table, rows)
            state = _TableState(
                spec=table,
                relation_info=info,
                rows=rows,
                pk_column=pk_column,
                pk_strategy=table.primary_key.strategy,
                pk_start=table.primary_key.start or 1,
                pk_step=table.primary_key.step or 1,
                table_seed=table_seed,
                columns_by_name={column.name: column for column in table.columns},
            )
            return state, _simple_chunks(rows, chunk_size)

        max_allowed = (
            cardinality.MAX_THREAD_CARDINALITY
            if rows_from.relation == "thread"
            else cardinality.MAX_CARDINALITY
        )
        card_spec = _cardinality_spec_from_schema(rows_from, max_allowed=max_allowed)
        card_seed_col = seeds.seed_relation(table_seed, "card")
        parent_indices = np.arange(parent_state.rows, dtype=np.int64)
        card = cardinality.sample(card_spec, card_seed_col, parent_indices)
        cumulative = np.zeros(parent_state.rows + 1, dtype=np.int64)
        np.cumsum(card, out=cumulative[1:])
        rows = int(cumulative[-1])

        if rows_from.relation == "one_to_many":
            info = _OneToManyInfo(
                parent_table=parent_table,
                via_column=via_column.name,
                card_spec=card_spec,
                cumulative=cumulative,
            )
            never_split = False
        elif rows_from.relation == "many_to_many":
            if not isinstance(rows_from.pair, str):
                raise PlanError(f"'{table.name}.rows_from.pair' é obrigatório em many_to_many")
            pair_column = _find_column(table, rows_from.pair)
            if pair_column is None or pair_column.type != "ref":
                raise PlanError(f"'{table.name}.rows_from.pair' precisa ser uma coluna 'ref'")
            pair_table = str(pair_column.params["table"])
            pair_state = table_states.get(pair_table)
            if pair_state is None:
                raise PlanError(
                    f"tabela '{pair_table}' de '{table.name}.pair' não foi planejada ainda"
                )
            if card.size and int(card.max()) > pair_state.rows:
                raise PlanError(
                    f"'{table.name}': max(cardinalidade) ({int(card.max())}) excede "
                    f"|{pair_table}| ({pair_state.rows})"
                )
            info = _ManyToManyInfo(
                parent_table=parent_table,
                via_column=via_column.name,
                pair_table=pair_table,
                pair_column=pair_column.name,
                card_spec=card_spec,
                cumulative=cumulative,
                pair_key_base=seeds.derive(seeds.seed_relation(table_seed, "relation"), "pair"),
            )
            never_split = False
        elif rows_from.relation == "thread":
            info = self._build_thread_info(
                table, table_seed, via_column, parent_table, card_spec, cumulative
            )
            never_split = True
        else:  # pragma: no cover - forma inválida já rejeitada pelo pydantic
            raise PlanError(f"relação desconhecida: {rows_from.relation}")

        self._check_sequence_overflow(table, rows)
        state = _TableState(
            spec=table,
            relation_info=info,
            rows=rows,
            pk_column=pk_column,
            pk_strategy=table.primary_key.strategy,
            pk_start=table.primary_key.start or 1,
            pk_step=table.primary_key.step or 1,
            table_seed=table_seed,
            columns_by_name={column.name: column for column in table.columns},
        )
        chunks = _greedy_chunks(
            cumulative, chunk_size, never_split=never_split, parent_table=parent_table
        )
        return state, chunks

    def _build_thread_info(
        self,
        table: TableSpec,
        table_seed: int,
        via_column: ColumnSpec,
        parent_table: str,
        card_spec: cardinality.CardinalitySpec,
        cumulative: NDArray[np.int64],
    ) -> _ThreadInfo:
        thread = table.thread or {}
        participants_raw = thread.get("participants")
        if not isinstance(participants_raw, dict):
            raise PlanError(f"'{table.name}.thread.participants' é obrigatório")
        count = int(participants_raw.get("count", 0))
        if not (2 <= count <= 10):
            raise PlanError(f"'{table.name}.thread.participants.count' precisa estar em [2, 10]")
        participants = _ThreadParticipants(
            table=str(participants_raw["table"]),
            count=count,
            label_column=str(participants_raw.get("label_column", "")),
        )
        start_raw = cast("dict[str, object]", thread.get("start", {}))
        gap_raw = cast("dict[str, object]", thread.get("gap_seconds", {}))
        relation_base = seeds.seed_relation(table_seed, "relation")
        return _ThreadInfo(
            parent_table=parent_table,
            via_column=via_column.name,
            card_spec=card_spec,
            cumulative=cumulative,
            participants=participants,
            start_min_epoch=_iso_to_epoch_seconds(start_raw["min"]),
            start_max_epoch=_iso_to_epoch_seconds(start_raw["max"]),
            gap_min_seconds=int(cast(int, gap_raw.get("min", 1))),
            gap_max_seconds=int(cast(int, gap_raw.get("max", 1))),
            participants_key_base=seeds.derive(relation_base, "part"),
            author_key_base=seeds.derive(relation_base, "autor"),
            timestamp_key_base=seeds.derive(relation_base, "timestamp"),
        )

    def _check_sequence_overflow(self, table: TableSpec, rows: int) -> None:
        if table.primary_key.strategy != "sequence":
            return
        start = table.primary_key.start or 1
        step = table.primary_key.step or 1
        if keys.sequence_overflows(rows, start, step):
            raise PlanError(
                f"'{table.name}': chave 'sequence' estoura 2**63 com rows={rows}, "
                f"start={start}, step={step}"
            )

    # ----------------------------------------------------------------- pk_at

    def pk_at(self, table: str, indices: NDArray[np.int64]) -> pa.Array:
        state = self._require_table(table)
        indices = np.asarray(indices, dtype=np.int64)
        if state.pk_strategy == "sequence":
            return pa.array(keys.sequence_pk(indices, state.pk_start, state.pk_step))
        if state.pk_strategy == "seeded_int":
            return pa.array(
                keys.seeded_int_pk(indices, state.rows, state.table_seed, state.pk_start)
            )
        if state.pk_strategy == "seeded_uuid":
            return keys.seeded_uuid_pk(indices, state.table_seed)
        if state.pk_strategy == "composite":
            info = state.relation_info
            if not isinstance(info, _ManyToManyInfo):
                raise PlanError(f"'{table}' não tem chave composta válida")
            via_values = self._ref_column_values(
                state, state.columns_by_name[info.via_column], indices
            )
            pair_values = self._ref_column_values(
                state, state.columns_by_name[info.pair_column], indices
            )
            return pa.StructArray.from_arrays(
                [via_values, pair_values], names=[info.via_column, info.pair_column]
            )
        raise PlanError(f"estratégia de chave primária desconhecida: {state.pk_strategy}")

    # -------------------------------------------------------- parent_index_of

    def parent_index_of(self, table: str, chunk: ChunkSpec, batch: object) -> NDArray[np.int64]:
        state = self._require_table(table)
        rows = _batch_rows(batch)
        return self._dirigente_parent_indices(state, rows)

    # ----------------------------------------------------------------- row_at

    def row_at(
        self, table: str, indices: NDArray[np.int64], columns: list[str]
    ) -> dict[str, pa.Array]:
        state = self._require_table(table)
        indices = np.asarray(indices, dtype=np.int64)
        return {name: self._column_values_cached(state, name, indices) for name in columns}

    def _column_values_cached(
        self, state: _TableState, column_name: str, indices: NDArray[np.int64]
    ) -> pa.Array:
        chunks: list[pa.Array] = []
        for chunk_start in range(0, indices.shape[0], _LRU_CHUNK_SIZE) if indices.size else [0]:
            piece = (
                indices[chunk_start : chunk_start + _LRU_CHUNK_SIZE] if indices.size else indices
            )
            chunks.append(self._column_values_for_piece(state, column_name, piece))
        return pa.concat_arrays(chunks) if len(chunks) != 1 else chunks[0]

    def _column_values_for_piece(
        self, state: _TableState, column_name: str, indices: NDArray[np.int64]
    ) -> pa.Array:
        if indices.size == 0:
            return self._compute_column(state, column_name, indices)
        cache_key = (state.spec.name, column_name, int(indices[0]) // _LRU_CHUNK_SIZE)
        aligned = (
            indices.shape[0] <= _LRU_CHUNK_SIZE
            and int(indices[0]) % _LRU_CHUNK_SIZE == 0
            and (indices == np.arange(indices[0], indices[0] + indices.shape[0])).all()
        )
        if aligned and cache_key in self._row_cache:
            self._row_cache.move_to_end(cache_key)
            return self._row_cache[cache_key]
        values = self._compute_column(state, column_name, indices)
        if aligned:
            self._row_cache[cache_key] = values
            self._row_cache.move_to_end(cache_key)
            while len(self._row_cache) > _MAX_ROW_CACHE_CHUNKS:
                self._row_cache.popitem(last=False)
        return values

    def _compute_column(
        self, state: _TableState, column_name: str, indices: NDArray[np.int64]
    ) -> pa.Array:
        if column_name == state.pk_column:
            return self.pk_at(state.spec.name, indices)
        column = state.columns_by_name.get(column_name)
        if column is None:
            raise PlanError(f"coluna desconhecida: '{state.spec.name}.{column_name}'")
        if column.is_llm:
            raise PlanError(
                f"row_at não pode calcular a coluna não determinística '{column_name}' "
                f"(tipo '{column.type}')"
            )
        if (
            isinstance(state.relation_info, _ThreadInfo)
            and column_name in _THREAD_DETERMINISTIC_COLUMNS
        ):
            return self._thread_column(state, column_name, indices)
        if column.type == "ref":
            return self._ref_column_values(state, column, indices)
        generator = self.generators.get(column.type)
        if generator is None:
            raise PlanError(
                f"gerador desconhecido para o tipo '{column.type}' (coluna '{column_name}')"
            )
        draws = seeds.Draws(seed_col=seeds.seed_column(state.table_seed, column_name), rows=indices)
        ctx = _RowAtContext(
            planner=self, locale_value=column.locale or state.spec.locale or "pt_BR"
        )
        return generator.generate(column, RowBatch(rows=indices), draws, ctx)

    # ----------------------------------------------------------- ref helpers

    def _dirigente_parent_indices(
        self, state: _TableState, indices: NDArray[np.int64]
    ) -> NDArray[np.int64]:
        info = state.relation_info
        if isinstance(info, _OneToOneInfo):
            return np.asarray(
                feistel.perm(indices, info.parent_rows, info.perm_key), dtype=np.int64
            )
        if isinstance(info, _OneToManyInfo | _ManyToManyInfo):
            return (np.searchsorted(info.cumulative, indices, side="right") - 1).astype(np.int64)
        raise PlanError(f"tabela '{state.spec.name}' não tem uma relação de pai definida")

    def _many_to_many_pair_indices(
        self, state: _TableState, info: _ManyToManyInfo, indices: NDArray[np.int64]
    ) -> NDArray[np.int64]:
        parent_indices = self._dirigente_parent_indices(state, indices)
        local_position = indices - info.cumulative[parent_indices]
        row_keys = np.array(
            [seeds.derive(info.pair_key_base, f"pair:{j}") for j in parent_indices.tolist()],
            dtype=np.uint64,
        )
        pair_table_rows = self._require_table(info.pair_table).rows
        return np.asarray(feistel.perm(local_position, pair_table_rows, row_keys), dtype=np.int64)

    def _non_dirigente_parent_indices(
        self, state: _TableState, column: ColumnSpec, indices: NDArray[np.int64]
    ) -> NDArray[np.int64]:
        target_table = str(column.params["table"])
        population = self._require_table(target_table).rows
        seed_col = seeds.seed_column(state.table_seed, column.name)
        distribution = column.params.get("distribution")
        shuffle = column.params.get("shuffle", True)
        if isinstance(distribution, dict) and isinstance(distribution.get("zipf"), dict):
            s = float(distribution["zipf"]["s"])
            rank0 = _zipf.rank(seed_col, indices, 0, s, population)
        else:
            rank0 = seeds.choice(seed_col, indices, 0, population)
        if shuffle:
            key = seeds.derive(seed_col, "shuffle")
            return np.asarray(feistel.perm(rank0, population, key), dtype=np.int64)
        return rank0

    def _ref_column_values(
        self, state: _TableState, column: ColumnSpec, indices: NDArray[np.int64]
    ) -> pa.Array:
        target_table = str(column.params["table"])
        info = state.relation_info
        if isinstance(info, _ManyToManyInfo) and column.name == info.pair_column:
            parent_indices = self._many_to_many_pair_indices(state, info, indices)
        elif getattr(info, "via_column", None) == column.name:
            parent_indices = self._dirigente_parent_indices(state, indices)
        else:
            parent_indices = self._non_dirigente_parent_indices(state, column, indices)
        return self.pk_at(target_table, parent_indices)

    # -------------------------------------------------------- thread helpers

    def _thread_column(
        self, state: _TableState, column_name: str, indices: NDArray[np.int64]
    ) -> pa.Array:
        info = state.relation_info
        assert isinstance(info, _ThreadInfo)
        thread_indices = self._dirigente_parent_indices(state, indices)
        local_seq = (indices - info.cumulative[thread_indices]).astype(np.int64)  # 0-indexed

        if column_name == "seq":
            return pa.array((local_seq + 1).astype(np.int32), type=pa.int32())

        unique_threads = np.unique(thread_indices)
        max_len = (
            int((info.cumulative[unique_threads + 1] - info.cumulative[unique_threads]).max())
            if unique_threads.size
            else 0
        )
        authors_by_thread, timestamps_by_thread = self._thread_sequences(
            state, info, unique_threads, max_len
        )
        thread_position = {int(j): position for position, j in enumerate(unique_threads.tolist())}
        row_positions = np.array([thread_position[int(j)] for j in thread_indices.tolist()])

        if column_name == "autor":
            author_local = authors_by_thread[row_positions, local_seq]
            author_global = np.asarray(
                feistel.perm(
                    author_local,
                    self._require_table(info.participants.table).rows,
                    np.array(
                        [
                            seeds.derive(info.participants_key_base, f"part:{j}")
                            for j in thread_indices.tolist()
                        ],
                        dtype=np.uint64,
                    ),
                ),
                dtype=np.int64,
            )
            return self.pk_at(info.participants.table, author_global)

        if column_name == "timestamp":
            epoch_seconds = timestamps_by_thread[row_positions, local_seq]
            return pa.array(epoch_seconds.astype("int64") * 1000, type=pa.timestamp("ms"))

        raise PlanError(f"coluna de thread desconhecida: '{column_name}'")  # pragma: no cover

    def _thread_sequences(
        self,
        state: _TableState,
        info: _ThreadInfo,
        unique_threads: NDArray[np.int64],
        max_len: int,
    ) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        num_threads = unique_threads.shape[0]
        authors = np.zeros((num_threads, max_len), dtype=np.int64)
        timestamps = np.zeros((num_threads, max_len), dtype=np.int64)
        if num_threads == 0:
            return authors, timestamps

        lengths = (info.cumulative[unique_threads + 1] - info.cumulative[unique_threads]).astype(
            np.int64
        )
        start_seed = seeds.seed_relation(state.table_seed, "thread:start")
        gap_seed = seeds.seed_relation(state.table_seed, "thread:gap")
        author_seed = seeds.seed_relation(state.table_seed, "thread:author")

        authors[:, 0] = 0
        timestamps[:, 0] = seeds.integers(
            start_seed, unique_threads, 0, info.start_min_epoch, info.start_max_epoch + 1
        )
        for position in range(1, max_len):
            active = position < lengths
            active_threads = unique_threads[active]
            if active_threads.size == 0:
                continue
            offset = seeds.integers(
                author_seed, active_threads, position, 1, info.participants.count
            )
            authors[active, position] = (
                authors[active, position - 1] + offset
            ) % info.participants.count
            gaps = seeds.integers(
                gap_seed, active_threads, position, info.gap_min_seconds, info.gap_max_seconds + 1
            )
            timestamps[active, position] = timestamps[active, position - 1] + gaps
        return authors, timestamps

    # ---------------------------------------------------------------- utils

    def _require_table(self, table: str) -> _TableState:
        if table not in self._tables:
            raise PlanError(f"tabela '{table}' não foi planejada; chame plan() antes de recalcular")
        return self._tables[table]


@dataclass
class _RowAtContext:
    planner: RelationsPlanner
    locale_value: str
    _same_row_values: dict[str, pa.Array] = field(default_factory=dict)

    @property
    def locale(self) -> str:
        return self.locale_value

    def same_row(self, column_names: list[str]) -> dict[str, pa.Array]:
        return {name: self._same_row_values[name] for name in column_names}

    def parent_rows(
        self, table: str, parent_indices: NDArray[np.int64], columns: list[str]
    ) -> dict[str, pa.Array]:
        return self.planner.row_at(table, parent_indices, columns)


def _batch_rows(batch: object) -> NDArray[np.int64]:
    if isinstance(batch, RowBatch):
        return np.asarray(batch.rows, dtype=np.int64)
    if isinstance(batch, np.ndarray):
        return batch.astype(np.int64)
    return np.asarray(batch, dtype=np.int64)


def _simple_chunks(rows: int, chunk_size: int) -> tuple[ChunkSpec, ...]:
    boundaries = range(0, rows, chunk_size) if rows else ()
    return tuple(
        ChunkSpec(id=chunk_id, first_row=first_row, rows=min(chunk_size, rows - first_row))
        for chunk_id, first_row in enumerate(boundaries)
    )


def _greedy_chunks(
    cumulative: NDArray[np.int64], chunk_size: int, *, never_split: bool, parent_table: str
) -> tuple[ChunkSpec, ...]:
    """Agrupa pais em chunks de <= `chunk_size` filhos (DD-01 §B.3.4).

    Um único pai maior que `chunk_size` é partido em sub-chunks, exceto
    quando `never_split` (threads, §B.3.6): nesse caso o chunk sozinho pode
    exceder `chunk_size`.
    """
    num_parents = cumulative.shape[0] - 1
    chunks: list[ChunkSpec] = []
    chunk_id = 0
    parent_ptr = 0
    while parent_ptr < num_parents:
        start_row = int(cumulative[parent_ptr])
        own_card = int(cumulative[parent_ptr + 1] - cumulative[parent_ptr])
        if own_card > chunk_size and not never_split:
            sub_offset = 0
            while sub_offset < own_card:
                take = min(chunk_size, own_card - sub_offset)
                chunks.append(
                    ChunkSpec(
                        id=chunk_id,
                        first_row=start_row + sub_offset,
                        rows=take,
                        parent=ParentRef(
                            table=parent_table,
                            first_index=parent_ptr,
                            count=1,
                            first_child_offset=sub_offset,
                        ),
                    )
                )
                chunk_id += 1
                sub_offset += take
            parent_ptr += 1
            continue

        total = own_card
        next_parent = parent_ptr + 1
        while next_parent < num_parents:
            next_card = int(cumulative[next_parent + 1] - cumulative[next_parent])
            if total + next_card > chunk_size:
                break
            total += next_card
            next_parent += 1
        chunks.append(
            ChunkSpec(
                id=chunk_id,
                first_row=start_row,
                rows=total,
                parent=ParentRef(
                    table=parent_table,
                    first_index=parent_ptr,
                    count=next_parent - parent_ptr,
                    first_child_offset=0,
                ),
            )
        )
        chunk_id += 1
        parent_ptr = next_parent
    return tuple(chunks)
