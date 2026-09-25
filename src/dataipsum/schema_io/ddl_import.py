"""Import de DDL SQL (`CREATE TABLE`/`ALTER TABLE ... ADD PRIMARY|FOREIGN KEY`, DD-02 §F.3.4).

O SQL **nunca é executado** e nenhuma conexão é aberta: só `sqlglot.parse` sobre o
texto. O resultado passa por `dataipsum.schema.loader.load_schema` antes de ser
devolvido, então o `Schema` produzido já é estruturalmente válido (DD-00 §3.3).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import reduce
from typing import TypeGuard, cast

import sqlglot
from sqlglot import exp

from dataipsum.errors import SchemaError, ValidationError
from dataipsum.schema.loader import load_schema
from dataipsum.schema.models import Schema
from dataipsum.schema_io.graph import topological_order

MAX_IMPORT_SQL_BYTES = 5 * 1024 * 1024
MAX_IMPORT_TABLES = 200
MAX_IMPORT_COLUMNS_PER_TABLE = 500

_TEXTUAL_TYPE_NAMES = frozenset({"string", "char"})

_INT_RANGES: dict[str, tuple[int, int]] = {
    "SMALLINT": (-32_768, 32_767),
    "INT": (-2_147_483_648, 2_147_483_647),
    "BIGINT": (-9_223_372_036_854_775_808, 9_223_372_036_854_775_807),
}

_DEFAULT_TEXT_MAX_LENGTH = 255
_DEFAULT_EMAIL_MAX_LENGTH = 254
_MYSQL_UUID_CHAR_LENGTH = 36

_LLM_PLACEHOLDER_CONFIG: dict[str, object] = {
    "default_provider": "local",
    "providers": {
        "local": {"kind": "ollama", "model": "ajuste-me", "base_url": "http://localhost:11434"}
    },
}


@dataclass(frozen=True)
class ImportReport:
    """Achados do import de DDL (DD-02 §F.3.4): inferências, TODOs e comandos ignorados."""

    findings: tuple[str, ...] = ()

    def render_yaml_comment_block(self) -> str:
        """Bloco de comentários "Revise:" (§F.3.4) para preceder o YAML emitido."""
        if not self.findings:
            return ""
        body = "\n".join(f"#   {finding}" for finding in self.findings)
        return f"# Revise:\n{body}\n"


@dataclass(frozen=True)
class _RawColumn:
    name: str
    data_type: exp.DataType
    is_not_null: bool
    is_unique: bool
    is_auto_increment: bool
    is_inline_pk: bool
    inline_reference: tuple[str, str] | None


@dataclass(frozen=True)
class _RawForeignKey:
    column: str
    target_table: str
    target_column: str


@dataclass(frozen=True)
class _RawTable:
    name: str
    columns: tuple[_RawColumn, ...]
    pk_columns: tuple[str, ...]
    foreign_keys: tuple[_RawForeignKey, ...]


@dataclass(frozen=True)
class _ImportedType:
    type_name: str
    max_length: int | None = None
    params: Mapping[str, object] = field(default_factory=dict)
    format: str | None = None
    is_integer: bool = False
    is_uuid: bool = False


def _statement_line_numbers(sql_text: str) -> list[int]:
    """Linha (1-based) aproximada de início de cada comando (separado por ';').

    `sqlglot.parse` também separa comandos por ';' fora de literais/comentários; listar a
    linha exata exigiria retokenizar com posições, custo desproporcional para um aviso
    informativo sobre comandos ignorados (§F.3.4).
    """
    line = 1
    line_numbers = []
    for chunk in sql_text.split(";"):
        if chunk.strip():
            line_numbers.append(line)
        line += chunk.count("\n")
    return line_numbers


def _is_create_table(statement: exp.Expression) -> TypeGuard[exp.Create]:
    return isinstance(statement, exp.Create) and str(statement.kind or "").upper() == "TABLE"


def _parse_statements(sql_text: str, dialect: str) -> list[exp.Expression]:
    try:
        parsed = sqlglot.parse(sql_text, read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise SchemaError(
            [ValidationError(path="$", message=f"DDL inválido para o dialeto '{dialect}': {exc}")]
        ) from exc
    return [cast(exp.Expression, statement) for statement in parsed if statement is not None]


def _column_constraint_kinds(column_def: exp.ColumnDef) -> list[exp.Expression]:
    return [cast(exp.Expression, constraint.kind) for constraint in (column_def.constraints or [])]


def _reference_target(reference: exp.Reference) -> tuple[str, str]:
    ref_schema = cast(exp.Schema, reference.this)
    return ref_schema.this.name, ref_schema.expressions[0].name


def _extract_raw_column(column_def: exp.ColumnDef) -> _RawColumn:
    kinds = _column_constraint_kinds(column_def)
    reference = next((kind for kind in kinds if isinstance(kind, exp.Reference)), None)
    inline_reference = _reference_target(reference) if reference is not None else None
    data_type = column_def.kind
    if data_type is None:
        raise SchemaError(
            [
                ValidationError(
                    path=f"columns.{column_def.name}", message="coluna sem tipo SQL declarado"
                )
            ]
        )
    return _RawColumn(
        name=column_def.name,
        data_type=data_type,
        is_not_null=any(isinstance(kind, exp.NotNullColumnConstraint) for kind in kinds),
        is_unique=any(isinstance(kind, exp.UniqueColumnConstraint) for kind in kinds),
        is_auto_increment=any(
            isinstance(kind, exp.AutoIncrementColumnConstraint) for kind in kinds
        ),
        is_inline_pk=any(isinstance(kind, exp.PrimaryKeyColumnConstraint) for kind in kinds),
        inline_reference=inline_reference,
    )


def _table_level_unique_column_names(expressions: Sequence[exp.Expression]) -> frozenset[str]:
    return frozenset(
        identifier.name
        for expression in expressions
        if isinstance(expression, exp.UniqueColumnConstraint) and expression.this is not None
        for identifier in expression.this.expressions
    )


def _table_level_pk_columns(expressions: Sequence[exp.Expression]) -> tuple[str, ...]:
    primary_key = next((e for e in expressions if isinstance(e, exp.PrimaryKey)), None)
    return tuple(identifier.name for identifier in primary_key.expressions) if primary_key else ()


def _foreign_key_reference(foreign_key: exp.ForeignKey) -> exp.Reference:
    return cast(exp.Reference, foreign_key.args["reference"])


def _table_level_foreign_keys(expressions: Sequence[exp.Expression]) -> tuple[_RawForeignKey, ...]:
    return tuple(
        _RawForeignKey(
            column=fk.expressions[0].name,
            target_table=(target := _reference_target(_foreign_key_reference(fk)))[0],
            target_column=target[1],
        )
        for fk in expressions
        if isinstance(fk, exp.ForeignKey)
    )


def _extract_raw_table(create: exp.Create) -> _RawTable:
    schema_expression = create.this
    table_expressions = schema_expression.expressions
    raw_columns = [
        _extract_raw_column(e) for e in table_expressions if isinstance(e, exp.ColumnDef)
    ]
    unique_from_table_constraints = _table_level_unique_column_names(table_expressions)
    columns = tuple(
        replace(c, is_unique=c.is_unique or c.name in unique_from_table_constraints)
        for c in raw_columns
    )
    pk_columns = _table_level_pk_columns(table_expressions) or tuple(
        c.name for c in columns if c.is_inline_pk
    )
    inline_foreign_keys = tuple(
        _RawForeignKey(
            column=c.name, target_table=c.inline_reference[0], target_column=c.inline_reference[1]
        )
        for c in columns
        if c.inline_reference is not None
    )
    foreign_keys = inline_foreign_keys + _table_level_foreign_keys(table_expressions)
    return _RawTable(
        name=schema_expression.this.name,
        columns=columns,
        pk_columns=pk_columns,
        foreign_keys=foreign_keys,
    )


def _alter_additions(alter: exp.Alter) -> tuple[str, tuple[str, ...] | None, _RawForeignKey | None]:
    table_name = alter.this.name
    actions = alter.args.get("actions", [])
    pk_action = next((found for a in actions if (found := a.find(exp.PrimaryKey))), None)
    fk_action = next((found for a in actions if (found := a.find(exp.ForeignKey))), None)
    pk_columns = (
        tuple(identifier.name for identifier in pk_action.expressions) if pk_action else None
    )
    foreign_key = (
        _RawForeignKey(
            column=fk_action.expressions[0].name,
            target_table=_reference_target(_foreign_key_reference(fk_action))[0],
            target_column=_reference_target(_foreign_key_reference(fk_action))[1],
        )
        if fk_action
        else None
    )
    return table_name, pk_columns, foreign_key


def _merge_alter_addition(
    tables_by_name: Mapping[str, _RawTable],
    addition: tuple[str, tuple[str, ...] | None, _RawForeignKey | None],
) -> dict[str, _RawTable]:
    table_name, pk_columns, foreign_key = addition
    table = tables_by_name.get(table_name)
    if table is None:
        return dict(tables_by_name)
    updated = replace(
        table,
        pk_columns=pk_columns if pk_columns is not None else table.pk_columns,
        foreign_keys=(table.foreign_keys + (foreign_key,))
        if foreign_key is not None
        else table.foreign_keys,
    )
    return {**tables_by_name, table_name: updated}


def _apply_alter_additions(
    tables_by_name: Mapping[str, _RawTable], alters: Sequence[exp.Alter]
) -> dict[str, _RawTable]:
    additions = [_alter_additions(alter) for alter in alters]
    return reduce(_merge_alter_addition, additions, dict(tables_by_name))


def _normalize_identifier(name: str) -> str:
    lowered = re.sub(r"[^a-z0-9_]", "_", name.lower())
    prefixed = f"_{lowered}" if lowered[:1].isdigit() else lowered
    return (prefixed or "_")[:63]


def _rename_finding(kind: str, original: str, normalized: str) -> str | None:
    if original == normalized:
        return None
    return f"{kind} '{original}' normalizada para '{normalized}' (identificador inválido)"


def _rename_findings(kind: str, name_map: Mapping[str, str]) -> list[str]:
    return [
        finding
        for original, normalized in name_map.items()
        for finding in [_rename_finding(kind, original, normalized)]
        if finding is not None
    ]


def _raise_if_collision(label: str, name_map: Mapping[str, str]) -> None:
    values = list(name_map.values())
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise SchemaError(
            [
                ValidationError(
                    path=label,
                    message=f"colisão de identificadores após normalização: {duplicates}",
                )
            ]
        )


def _rebuild_table_with_normalized_names(table: _RawTable) -> _RawTable:
    columns = tuple(
        replace(
            c,
            name=_normalize_identifier(c.name),
            inline_reference=(
                (
                    _normalize_identifier(c.inline_reference[0]),
                    _normalize_identifier(c.inline_reference[1]),
                )
                if c.inline_reference is not None
                else None
            ),
        )
        for c in table.columns
    )
    foreign_keys = tuple(
        replace(
            fk,
            column=_normalize_identifier(fk.column),
            target_table=_normalize_identifier(fk.target_table),
            target_column=_normalize_identifier(fk.target_column),
        )
        for fk in table.foreign_keys
    )
    return replace(
        table,
        name=_normalize_identifier(table.name),
        columns=columns,
        pk_columns=tuple(_normalize_identifier(name) for name in table.pk_columns),
        foreign_keys=foreign_keys,
    )


def _normalize_table(table: _RawTable) -> tuple[_RawTable, list[str]]:
    column_name_map = {c.name: _normalize_identifier(c.name) for c in table.columns}
    _raise_if_collision(f"colunas de '{table.name}'", column_name_map)
    return _rebuild_table_with_normalized_names(table), _rename_findings("coluna", column_name_map)


def _normalize_names(raw_tables: Sequence[_RawTable]) -> tuple[dict[str, _RawTable], list[str]]:
    table_name_map = {table.name: _normalize_identifier(table.name) for table in raw_tables}
    _raise_if_collision("tabelas", table_name_map)
    table_findings = _rename_findings("tabela", table_name_map)
    normalized_pairs = [_normalize_table(table) for table in raw_tables]
    normalized_tables = {table.name: table for table, _ in normalized_pairs}
    column_findings = [finding for _, findings in normalized_pairs for finding in findings]
    return normalized_tables, table_findings + column_findings


def _int_param(data_type: exp.DataType, index: int) -> int | None:
    expressions = data_type.expressions
    if index >= len(expressions):
        return None
    param = expressions[index]
    literal = param.this if isinstance(param, exp.DataTypeParam) else param
    return int(literal.this) if isinstance(literal, exp.Literal) else None


def _map_sql_type(data_type: exp.DataType, column_name: str) -> tuple[_ImportedType, str | None]:
    kind_name = data_type.this.name
    if kind_name == "VARCHAR":
        length = _int_param(data_type, 0)
        if length is None:
            return (
                _ImportedType("string", max_length=_DEFAULT_TEXT_MAX_LENGTH),
                f"coluna '{column_name}': VARCHAR sem tamanho; max_length: "
                f"{_DEFAULT_TEXT_MAX_LENGTH} (TODO: ajuste)",
            )
        return _ImportedType("string", max_length=length), None
    if kind_name == "TEXT":
        return (
            _ImportedType("string", max_length=_DEFAULT_TEXT_MAX_LENGTH),
            f"coluna '{column_name}': TEXT sem tamanho; max_length: {_DEFAULT_TEXT_MAX_LENGTH} "
            "(TODO: ajuste)",
        )
    if kind_name == "CHAR" and _int_param(data_type, 0) == _MYSQL_UUID_CHAR_LENGTH:
        # MySQL não tem tipo UUID nativo; a trilha F exporta uuid como CHAR(36) (§F.3.1),
        # então reconhece esse comprimento exato na volta para preservar o round-trip.
        return _ImportedType("uuid", is_uuid=True), None
    if kind_name == "CHAR":
        return _ImportedType("char", max_length=_int_param(data_type, 0) or 1), None
    if kind_name in ("SERIAL", "BIGSERIAL"):
        return _ImportedType("int", is_integer=True), None
    if kind_name == "TINYINT" and _int_param(data_type, 0) == 1:
        return _ImportedType("boolean"), None
    if kind_name in _INT_RANGES:
        lo, hi = _INT_RANGES[kind_name]
        return _ImportedType("int", params={"min": lo, "max": hi}, is_integer=True), None
    if kind_name == "TINYINT":
        return _ImportedType("int", params={"min": -128, "max": 127}, is_integer=True), None
    if kind_name in ("FLOAT", "DOUBLE"):
        return _ImportedType("float"), None
    if kind_name == "DECIMAL":
        precision = _int_param(data_type, 0) or 10
        scale = _int_param(data_type, 1) or 2
        return _ImportedType("decimal", params={"precision": precision, "scale": scale}), None
    if kind_name == "BOOLEAN":
        return _ImportedType("boolean"), None
    if kind_name == "DATE":
        return _ImportedType("date"), None
    if kind_name == "TIME":
        return _ImportedType("time"), None
    if kind_name in ("TIMESTAMP", "DATETIME"):
        return _ImportedType("timestamp"), None
    if kind_name == "TIMESTAMPTZ":
        return _ImportedType("timestamp", params={"timezone": True}), None
    if kind_name == "UUID":
        return _ImportedType("uuid", is_uuid=True), None
    if kind_name in ("JSON", "JSONB"):
        return (
            _ImportedType("json", params={"exemplo": {"valor": "TODO"}}),
            f"coluna '{column_name}': JSON/JSONB recebeu params.exemplo de exemplo (TODO: ajuste)",
        )
    if kind_name == "ARRAY":
        nested = data_type.expressions[0] if data_type.expressions else None
        item_type_name = (
            _map_sql_type(nested, column_name)[0].type_name
            if isinstance(nested, exp.DataType)
            else "string"
        )
        return _ImportedType("array", params={"item": item_type_name}), None
    return (
        _ImportedType("string", max_length=_DEFAULT_TEXT_MAX_LENGTH),
        f"coluna '{column_name}': tipo SQL '{kind_name}' desconhecido; importado como string "
        f"com max_length: {_DEFAULT_TEXT_MAX_LENGTH} (aviso)",
    )


def _matches_any(
    name: str,
    *,
    equals: frozenset[str] = frozenset(),
    suffixes: tuple[str, ...] = (),
    prefixes: tuple[str, ...] = (),
    contains: tuple[str, ...] = (),
) -> bool:
    return (
        name in equals
        or any(name.endswith(suffix) for suffix in suffixes)
        or any(name.startswith(prefix) for prefix in prefixes)
        or any(needle in name for needle in contains)
    )


def _looks_like_name_column(name: str) -> bool:
    return _matches_any(
        name, equals=frozenset({"nome", "nome_completo", "name", "full_name"}), suffixes=("_nome",)
    )


def _infer_semantic_type(
    column_name: str, imported: _ImportedType, sibling_column_names: Sequence[str]
) -> tuple[_ImportedType, str | None]:
    """Inferência de tipo por nome (§F.3.4), só para colunas de base textual."""
    if imported.type_name not in _TEXTUAL_TYPE_NAMES:
        return imported, None
    if _matches_any(column_name, equals=frozenset({"cpf"}), suffixes=("_cpf",), prefixes=("cpf_",)):
        length = imported.max_length or 11
        column_format = "unmasked" if length == 11 else "masked"
        return (
            _ImportedType("cpf", format=column_format),
            f"coluna '{column_name}': inferida como 'cpf' (format={column_format}) pelo nome",
        )
    if _matches_any(column_name, equals=frozenset({"rg"}), suffixes=("_rg",), prefixes=("rg_",)):
        return _ImportedType("rg"), f"coluna '{column_name}': inferida como 'rg' pelo nome"
    if _matches_any(column_name, contains=("cartao", "credit_card", "card_number")):
        return (
            _ImportedType("cartao_credito"),
            f"coluna '{column_name}': inferida como 'cartao_credito' pelo nome",
        )
    if _matches_any(
        column_name,
        equals=frozenset({"nome", "nome_completo", "name", "full_name"}),
        suffixes=("_nome",),
    ):
        is_first_name = column_name in ("first_name", "primeiro_nome")
        params: dict[str, object] = {"parts": "first"} if is_first_name else {}
        return (
            _ImportedType("nome_proprio", max_length=imported.max_length, params=params),
            f"coluna '{column_name}': inferida como 'nome_proprio' pelo nome",
        )
    if _matches_any(column_name, equals=frozenset({"email", "e_mail"}), suffixes=("_email",)):
        max_length = min(
            imported.max_length or _DEFAULT_EMAIL_MAX_LENGTH, _DEFAULT_EMAIL_MAX_LENGTH
        )
        name_column = next((c for c in sibling_column_names if _looks_like_name_column(c)), None)
        params = {"name_column": name_column} if name_column is not None else {}
        return (
            _ImportedType("email", max_length=max_length, params=params),
            f"coluna '{column_name}': inferida como 'email' (endereço) pelo nome, "
            f"max_length: {max_length}",
        )
    if _matches_any(column_name, equals=frozenset({"post"}), suffixes=("_post",)):
        return _ImportedType(
            "llm_post"
        ), f"coluna '{column_name}': inferida como 'llm_post' pelo nome"
    if _matches_any(column_name, contains=("contrato", "contract")):
        return (
            _ImportedType("llm_contrato"),
            f"coluna '{column_name}': inferida como 'llm_contrato' pelo nome",
        )
    return imported, None


def _null_ratio_finding(column: _RawColumn, *, is_primary_key: bool) -> str | None:
    if column.is_not_null or is_primary_key:
        return None
    return (
        f"coluna '{column.name}': era anulável no DDL de origem; importada com null_ratio: 0 "
        "(ajuste se a coluna deve aceitar nulos)"
    )


def _column_document(
    column: _RawColumn,
    ref_target_by_column: Mapping[str, str],
    sibling_column_names: Sequence[str],
) -> tuple[dict[str, object], str | None]:
    if column.name in ref_target_by_column:
        document: dict[str, object] = {
            "name": column.name,
            "type": "ref",
            "params": {"table": ref_target_by_column[column.name]},
            "null_ratio": 0,
        }
        return document, None

    base, base_finding = _map_sql_type(column.data_type, column.name)
    inferred, inference_finding = _infer_semantic_type(column.name, base, sibling_column_names)
    document = {"name": column.name, "type": inferred.type_name, "null_ratio": 0}
    if inferred.max_length is not None:
        document["max_length"] = inferred.max_length
    if inferred.format is not None:
        document["format"] = inferred.format
    if inferred.params:
        document["params"] = dict(inferred.params)
    finding = inference_finding or base_finding
    return document, finding


def _pk_strategy(table_name: str, pk_column_name: str, pk_type_name: str) -> str:
    if pk_type_name in ("int", "int32", "int64"):
        return "sequence"
    if pk_type_name == "uuid":
        return "seeded_uuid"
    raise SchemaError(
        [
            ValidationError(
                path=f"tables.{table_name}.primary_key",
                message=(
                    f"chave primária textual ('{pk_column_name}': '{pk_type_name}') não tem "
                    "estratégia de geração suportada; use uma coluna inteira (serial/int) ou "
                    "UUID como chave primária"
                ),
            )
        ]
    )


def _process_table(
    table: _RawTable, all_table_names: frozenset[str]
) -> tuple[dict[str, object], list[str], bool]:
    self_referencing_fks = [fk for fk in table.foreign_keys if fk.target_table == table.name]
    effective_fks = [fk for fk in table.foreign_keys if fk.target_table != table.name]
    findings = [
        f"tabela '{table.name}': coluna '{fk.column}' é auto-FK; importada como coluna simples "
        "(auto-relacionamento é não-objetivo do import)"
        for fk in self_referencing_fks
    ]

    missing_targets = sorted({fk.target_table for fk in effective_fks} - all_table_names)
    if missing_targets:
        raise SchemaError(
            [
                ValidationError(
                    path=f"tables.{table.name}",
                    message=f"FK para tabela inexistente no DDL importado: {missing_targets}",
                )
            ]
        )

    is_bridge = len(table.pk_columns) == 2 and {fk.column for fk in effective_fks} == set(
        table.pk_columns
    )
    if not is_bridge and len(table.pk_columns) > 1:
        raise SchemaError(
            [
                ValidationError(
                    path=f"tables.{table.name}.primary_key",
                    message=(
                        "chave primária composta só é suportada quando formada por exatamente 2 "
                        "chaves estrangeiras (tabela de associação many_to_many)"
                    ),
                )
            ]
        )

    ref_target_by_column = {fk.column: fk.target_table for fk in effective_fks}
    sibling_column_names = [c.name for c in table.columns]
    column_results = {
        column.name: _column_document(column, ref_target_by_column, sibling_column_names)
        for column in table.columns
    }
    column_documents = {name: document for name, (document, _) in column_results.items()}
    findings += [finding for _, finding in column_results.values() if finding is not None]
    findings += [
        finding
        for column in table.columns
        for finding in [_null_ratio_finding(column, is_primary_key=column.name in table.pk_columns)]
        if finding is not None
    ]
    has_llm_column = any(str(doc["type"]).startswith("llm_") for doc in column_documents.values())
    ordered_columns = [column_documents[c.name] for c in table.columns]

    if is_bridge:
        via_fk, pair_fk = effective_fks[0], effective_fks[1]
        table_document: dict[str, object] = {
            "name": table.name,
            "primary_key": {"columns": list(table.pk_columns), "strategy": "composite"},
            "rows_from": {
                "via": via_fk.column,
                "relation": "many_to_many",
                "pair": pair_fk.column,
                "cardinality": {"range": {"min": 1, "max": 3}},
            },
            "columns": ordered_columns,
        }
        return table_document, findings, has_llm_column

    pk_column_name = table.pk_columns[0]
    pk_strategy = _pk_strategy(
        table.name, pk_column_name, str(column_documents[pk_column_name]["type"])
    )
    table_document = {
        "name": table.name,
        "primary_key": {"columns": [pk_column_name], "strategy": pk_strategy},
        "columns": ordered_columns,
    }
    if effective_fks:
        via_fk = effective_fks[0]
        via_is_unique = next(c.is_unique for c in table.columns if c.name == via_fk.column)
        table_document["rows_from"] = (
            {"via": via_fk.column, "relation": "one_to_one", "coverage": 1.0}
            if via_is_unique
            else {
                "via": via_fk.column,
                "relation": "one_to_many",
                "cardinality": {"range": {"min": 0, "max": 5}},
            }
        )
    else:
        table_document["rows"] = 1000
    return table_document, findings, has_llm_column


def _raise_if_relation_cycle(tables: Sequence[_RawTable]) -> None:
    dependencies = {
        table.name: frozenset(
            fk.target_table for fk in table.foreign_keys if fk.target_table != table.name
        )
        for table in tables
    }
    try:
        topological_order(dependencies)
    except ValueError as exc:
        raise SchemaError(
            [ValidationError(path="tables", message=f"ciclo de relações entre tabelas: {exc}")]
        ) from exc


def _build_schema_document(tables: Mapping[str, _RawTable]) -> tuple[dict[str, object], list[str]]:
    ordered_tables = list(tables.values())
    _raise_if_relation_cycle(ordered_tables)
    all_table_names = frozenset(tables)
    processed = [_process_table(table, all_table_names) for table in ordered_tables]
    document: dict[str, object] = {
        "version": 1,
        "tables": [table_document for table_document, _, _ in processed],
    }
    findings = [finding for _, table_findings, _ in processed for finding in table_findings]
    if any(has_llm for _, _, has_llm in processed):
        document["llm"] = _LLM_PLACEHOLDER_CONFIG
        findings.append(
            "schema recebeu uma seção 'llm' placeholder (provider 'local', model 'ajuste-me') "
            "porque colunas llm_* foram inferidas pelo nome; ajuste antes de gerar dados"
        )
    return document, findings


def _check_size_limit(sql_text: str) -> None:
    size = len(sql_text.encode("utf-8"))
    if size > MAX_IMPORT_SQL_BYTES:
        raise SchemaError(
            [
                ValidationError(
                    path="$",
                    message=f"DDL excede o limite de {MAX_IMPORT_SQL_BYTES} bytes ({size} bytes)",
                )
            ]
        )


def _check_table_limits(tables: Sequence[_RawTable]) -> None:
    if len(tables) > MAX_IMPORT_TABLES:
        raise SchemaError(
            [
                ValidationError(
                    path="tables",
                    message=f"no máximo {MAX_IMPORT_TABLES} tabelas, recebido {len(tables)}",
                )
            ]
        )
    over_limit = sorted(t.name for t in tables if len(t.columns) > MAX_IMPORT_COLUMNS_PER_TABLE)
    if over_limit:
        raise SchemaError(
            [
                ValidationError(
                    path="tables",
                    message=(
                        f"tabelas com mais de {MAX_IMPORT_COLUMNS_PER_TABLE} colunas: {over_limit}"
                    ),
                )
            ]
        )


def import_ddl(sql_text: str, dialect: str) -> tuple[Schema, ImportReport]:
    """Importa `Schema` a partir de DDL SQL (DD-02 §F.3.4, §F.4, M3).

    Considera só `CREATE TABLE` e `ALTER TABLE ... ADD [CONSTRAINT] PRIMARY KEY/FOREIGN KEY`;
    os demais comandos são ignorados e listados no `ImportReport`. O SQL nunca é executado.
    """
    _check_size_limit(sql_text)
    statements = _parse_statements(sql_text, dialect)
    line_numbers = _statement_line_numbers(sql_text)
    ignored_findings = [
        f"linha {line}: comando '{type(statement).__name__}' ignorado (só CREATE TABLE e ALTER "
        "TABLE ADD PRIMARY/FOREIGN KEY são considerados)"
        for statement, line in zip(statements, line_numbers, strict=False)
        if not _is_create_table(statement) and not isinstance(statement, exp.Alter)
    ]
    creates = [statement for statement in statements if _is_create_table(statement)]
    alters = [statement for statement in statements if isinstance(statement, exp.Alter)]
    raw_tables = [_extract_raw_table(create) for create in creates]
    _check_table_limits(raw_tables)
    tables_by_name = {table.name: table for table in raw_tables}
    tables_with_alters = _apply_alter_additions(tables_by_name, alters)
    normalized_tables, rename_findings = _normalize_names(list(tables_with_alters.values()))
    document, build_findings = _build_schema_document(normalized_tables)
    schema = load_schema(document)
    return schema, ImportReport(findings=tuple(ignored_findings + rename_findings + build_findings))
