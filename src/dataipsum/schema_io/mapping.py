"""Deriva o `LogicalType` (DD-00 §3.5) de uma coluna do schema dataIpsum.

Como as trilhas A (tipos/geradores) não existem neste marco, este módulo não depende
de `dataipsum.types`/`Generator.logical_type`: ele deriva o `LogicalType` diretamente
dos campos de `ColumnSpec` (`type`, `max_length`, `params`, `null_ratio`, `format`),
usando os nomes de tipo já usados no exemplo do DD-00 §3.3 e nas tabelas F.3.1/F.3.2
do DD-02. Quando a trilha A existir, `ddl_for`/`avro_schema` podem trocar esta função
por `Generator.logical_type` sem mudar o resto da trilha F.
"""

from __future__ import annotations

from collections.abc import Mapping

from dataipsum.contracts import types as logical
from dataipsum.errors import SchemaError, ValidationError
from dataipsum.schema.models import ColumnSpec, Schema, TableSpec

DEFAULT_NOME_PROPRIO_MAX_LENGTH = 120
DEFAULT_EMAIL_MAX_LENGTH = 254
DEFAULT_CARTAO_CREDITO_MAX_LENGTH = 19
DEFAULT_DECIMAL_PRECISION = 10
DEFAULT_DECIMAL_SCALE = 2

# CPF/RG "unmasked" = só dígitos; "masked" = com pontuação (dv incluído nos dois).
CPF_LENGTH_UNMASKED = 11
CPF_LENGTH_MASKED = 14
RG_LENGTH_UNMASKED = 9
RG_LENGTH_MASKED = 12

TEXTUAL_KINDS = frozenset({"string", "text", "char"})


def find_table(schema: Schema, name: str) -> TableSpec:
    for table in schema.tables:
        if table.name == name:
            return table
    raise SchemaError(
        [ValidationError(path="tables", message=f"tabela referenciada não existe: '{name}'")]
    )


def _cpf_length(column: ColumnSpec) -> int:
    return CPF_LENGTH_UNMASKED if column.format != "masked" else CPF_LENGTH_MASKED


def _rg_length(column: ColumnSpec) -> int:
    return RG_LENGTH_UNMASKED if column.format != "masked" else RG_LENGTH_MASKED


def _coerce_int(value: object, default: int) -> int:
    return value if isinstance(value, int) else default


def _decimal_params(column: ColumnSpec) -> tuple[int, int]:
    precision = _coerce_int(column.params.get("precision"), DEFAULT_DECIMAL_PRECISION)
    scale = _coerce_int(column.params.get("scale"), DEFAULT_DECIMAL_SCALE)
    return precision, scale


def _array_item_logical_type(
    schema: Schema, table: TableSpec, params: Mapping[str, object]
) -> logical.LogicalType:
    item_spec = params.get("item")
    if isinstance(item_spec, str):
        item_column = ColumnSpec(name="item", type=item_spec)
    elif isinstance(item_spec, Mapping):
        item_column = ColumnSpec.model_validate({"name": "item", **item_spec})
    else:
        raise SchemaError(
            [
                ValidationError(
                    path=f"{table.name}.params.item",
                    message="coluna 'array' precisa de 'params.item' (nome de tipo ou objeto "
                    "de coluna)",
                )
            ]
        )
    return logical_type_for_column(schema, table, item_column)


def _logical_type_for_ref(
    schema: Schema, column: ColumnSpec, *, nullable: bool
) -> logical.LogicalType:
    target_table_name = str(column.params.get("table", ""))
    target_table = find_table(schema, target_table_name)
    target_pk_column_name = target_table.primary_key.columns[0]
    target_column = next((c for c in target_table.columns if c.name == target_pk_column_name), None)
    if target_column is None:
        raise SchemaError(
            [
                ValidationError(
                    path=f"{target_table_name}.{target_pk_column_name}",
                    message="coluna de chave primária referenciada não existe",
                )
            ]
        )
    target_logical = logical_type_for_column(schema, target_table, target_column)
    return logical.LogicalType(
        kind=target_logical.kind,
        max_length=target_logical.max_length,
        length=target_logical.length,
        precision=target_logical.precision,
        scale=target_logical.scale,
        tz=target_logical.tz,
        item=target_logical.item,
        max_items=target_logical.max_items,
        nullable=nullable,
    )


def logical_type_for_column(
    schema: Schema, table: TableSpec, column: ColumnSpec
) -> logical.LogicalType:
    """Mapeamento `ColumnSpec` -> `LogicalType`, usado por `ddl_for` e `avro_schema`."""
    nullable = column.null_ratio > 0
    kind = column.type

    if kind == "ref":
        return _logical_type_for_ref(schema, column, nullable=nullable)
    if kind == "string":
        if column.max_length is None:
            raise SchemaError(
                [
                    ValidationError(
                        path=f"{table.name}.{column.name}.max_length",
                        message="coluna 'string' exige 'max_length'",
                    )
                ]
            )
        return logical.string(column.max_length, nullable=nullable)
    if kind == "text":
        return logical.text(nullable=nullable)
    if kind == "cpf":
        return logical.char(_cpf_length(column), nullable=nullable)
    if kind == "rg":
        return logical.char(_rg_length(column), nullable=nullable)
    if kind == "cartao_credito":
        return logical.string(
            column.max_length or DEFAULT_CARTAO_CREDITO_MAX_LENGTH, nullable=nullable
        )
    if kind == "nome_proprio":
        return logical.string(
            column.max_length or DEFAULT_NOME_PROPRIO_MAX_LENGTH, nullable=nullable
        )
    if kind == "email":
        return logical.string(column.max_length or DEFAULT_EMAIL_MAX_LENGTH, nullable=nullable)
    if kind in ("int", "int64", "bigint"):
        return logical.int64(nullable=nullable)
    if kind == "int32":
        return logical.int32(nullable=nullable)
    if kind in ("float", "float64"):
        return logical.float64(nullable=nullable)
    if kind == "decimal":
        precision, scale = _decimal_params(column)
        return logical.decimal(precision, scale, nullable=nullable)
    if kind == "boolean":
        return logical.boolean(nullable=nullable)
    if kind == "date":
        return logical.date(nullable=nullable)
    if kind == "time":
        return logical.time(nullable=nullable)
    if kind == "timestamp":
        has_timezone = bool(column.params.get("timezone", False))
        return logical.timestamp(tz=has_timezone, nullable=nullable)
    if kind == "uuid":
        return logical.uuid(nullable=nullable)
    if kind == "json":
        return logical.json(nullable=nullable)
    if kind == "array":
        item = _array_item_logical_type(schema, table, column.params)
        max_items = column.params.get("max_items")
        return logical.array(
            item, int(max_items) if isinstance(max_items, int) else None, nullable=nullable
        )
    if kind.startswith("llm_"):
        if column.max_length is not None:
            return logical.string(column.max_length, nullable=nullable)
        return logical.text(nullable=nullable)
    raise SchemaError(
        [
            ValidationError(
                path=f"{table.name}.{column.name}.type",
                message=(
                    f"tipo de coluna '{kind}' não tem mapeamento de LogicalType conhecido pela "
                    "trilha F (import/export de schema)"
                ),
            )
        ]
    )
