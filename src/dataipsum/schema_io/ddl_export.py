"""Export de DDL SQL por dialeto (DD-02 §F.3.1, `ddl_for`).

Monta expressões `sqlglot` (`exp.Create`) e gera o SQL com `.sql(dialect=...)`;
nenhum nome entra no SQL por concatenação de string (DD-00 §6.2).
"""

from __future__ import annotations

import warnings

from sqlglot import exp

from dataipsum.contracts.types import LogicalType
from dataipsum.errors import SchemaError, ValidationError
from dataipsum.schema.models import ColumnSpec, Schema, TableSpec
from dataipsum.schema_io.graph import topological_order
from dataipsum.schema_io.mapping import find_table, logical_type_for_column

TESTED_DIALECTS = frozenset({"postgres", "mysql"})
FLAG_COLUMN_NAMES = frozenset({"is_offensive", "is_placeholder"})


def _quoted(name: str) -> exp.Identifier:
    return exp.to_identifier(name, quoted=True)


def _warn_if_dialect_untested(dialect: str) -> None:
    if dialect not in TESTED_DIALECTS:
        warnings.warn(
            f"dialeto '{dialect}' não é testado pela trilha F (só 'postgres' e 'mysql' são); "
            "o DDL gerado pode não ser válido nesse dialeto.",
            stacklevel=3,
        )


def _sql_type_for_logical(logical_type: LogicalType, dialect: str) -> str:
    is_postgres = dialect == "postgres"
    kind = logical_type.kind
    if kind == "string":
        return f"VARCHAR({logical_type.max_length})"
    if kind == "text":
        return "TEXT"
    if kind == "char":
        return f"CHAR({logical_type.length})"
    if kind == "int32":
        return "INTEGER" if is_postgres else "INT"
    if kind == "int64":
        return "BIGINT"
    if kind == "float64":
        return "DOUBLE PRECISION" if is_postgres else "DOUBLE"
    if kind == "decimal":
        return f"DECIMAL({logical_type.precision}, {logical_type.scale})"
    if kind == "boolean":
        return "BOOLEAN"
    if kind == "date":
        return "DATE"
    if kind == "time":
        return "TIME"
    if kind == "timestamp":
        if logical_type.tz:
            return "TIMESTAMPTZ(3)" if is_postgres else "TIMESTAMP(3)"
        return "TIMESTAMP(3)" if is_postgres else "DATETIME(3)"
    if kind == "uuid":
        return "UUID" if is_postgres else "CHAR(36)"
    if kind == "json":
        return "JSONB" if is_postgres else "JSON"
    if kind == "array":
        if logical_type.item is None:
            raise SchemaError(
                [ValidationError(path="type", message="LogicalType 'array' requer 'item'")]
            )
        if is_postgres:
            return f"{_sql_type_for_logical(logical_type.item, dialect)}[]"
        return "JSON"
    raise SchemaError([ValidationError(path="type", message=f"LogicalType desconhecido: {kind}")])


def _is_via_one_to_one(table: TableSpec, column: ColumnSpec) -> bool:
    rows_from = table.rows_from
    return (
        rows_from is not None
        and rows_from.relation == "one_to_one"
        and rows_from.via == column.name
    )


def _is_required_column(column: ColumnSpec) -> bool:
    return column.null_ratio == 0 or column.name in FLAG_COLUMN_NAMES


def _column_def(
    schema: Schema, table: TableSpec, column: ColumnSpec, dialect: str
) -> exp.ColumnDef:
    logical_type = logical_type_for_column(schema, table, column)
    data_type = exp.DataType.build(_sql_type_for_logical(logical_type, dialect), dialect=dialect)
    constraints = []
    if _is_required_column(column):
        constraints.append(exp.ColumnConstraint(kind=exp.NotNullColumnConstraint()))
    if _is_via_one_to_one(table, column):
        constraints.append(exp.ColumnConstraint(kind=exp.UniqueColumnConstraint()))
    return exp.ColumnDef(this=_quoted(column.name), kind=data_type, constraints=constraints or None)


def _primary_key_expression(table: TableSpec) -> exp.PrimaryKey:
    return exp.PrimaryKey(expressions=[_quoted(name) for name in table.primary_key.columns])


def _foreign_key_expressions(schema: Schema, table: TableSpec) -> list[exp.ForeignKey]:
    ref_columns = [column for column in table.columns if column.type == "ref"]
    return [
        exp.ForeignKey(
            expressions=[_quoted(column.name)],
            reference=exp.Reference(
                this=exp.Schema(
                    this=exp.Table(this=_quoted(target_table.name)),
                    expressions=[_quoted(target_table.primary_key.columns[0])],
                )
            ),
        )
        for column in ref_columns
        for target_table in [find_table(schema, str(column.params["table"]))]
    ]


def _create_table_expression(schema: Schema, table: TableSpec, dialect: str) -> exp.Create:
    columns = [_column_def(schema, table, column, dialect) for column in table.columns]
    table_constraints: list[exp.Expression] = [
        _primary_key_expression(table),
        *_foreign_key_expressions(schema, table),
    ]
    schema_expression = exp.Schema(
        this=exp.Table(this=_quoted(table.name)), expressions=[*columns, *table_constraints]
    )
    return exp.Create(this=schema_expression, kind="TABLE")


def _table_dependencies(schema: Schema, table: TableSpec) -> frozenset[str]:
    return frozenset(
        str(column.params["table"]) for column in table.columns if column.type == "ref"
    )


def _tables_in_topological_order(schema: Schema) -> list[TableSpec]:
    """Ordena as tabelas para que toda tabela referenciada por FK venha antes (§F.3.1)."""
    dependencies = {table.name: _table_dependencies(schema, table) for table in schema.tables}
    tables_by_name = {table.name: table for table in schema.tables}
    try:
        order = topological_order(dependencies)
    except ValueError as exc:
        raise SchemaError(
            [
                ValidationError(
                    path="tables", message=f"ciclo de referências (ref) entre tabelas: {exc}"
                )
            ]
        ) from exc
    return [tables_by_name[name] for name in order]


def ddl_for(schema: Schema, dialect: str) -> str:
    """DDL SQL (`CREATE TABLE` em ordem topológica) da trilha F (DD-02 §F.3.1).

    Sub-entrega prioritária consumida pela trilha E (`create_tables`, DD-02 E.3.2).
    """
    _warn_if_dialect_untested(dialect)
    statements = [
        _create_table_expression(schema, table, dialect)
        for table in _tables_in_topological_order(schema)
    ]
    return "".join(f"{statement.sql(dialect=dialect)};\n" for statement in statements)
