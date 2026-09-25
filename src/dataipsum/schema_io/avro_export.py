"""Export de Avro Schema por tabela (DD-02 §F.3.2, `avro_schema`)."""

from __future__ import annotations

from dataipsum.contracts.types import LogicalType
from dataipsum.errors import SchemaError, ValidationError
from dataipsum.schema.models import ColumnSpec, Schema, TableSpec
from dataipsum.schema_io.mapping import find_table, logical_type_for_column

AvroType = str | dict[str, object] | list[object]


def _avro_type_for_logical(logical_type: LogicalType) -> AvroType:
    kind = logical_type.kind
    if kind in ("string", "text", "char"):
        return "string"
    if kind == "int32":
        return "int"
    if kind == "int64":
        return "long"
    if kind == "float64":
        return "double"
    if kind == "decimal":
        return {
            "type": "bytes",
            "logicalType": "decimal",
            "precision": logical_type.precision,
            "scale": logical_type.scale,
        }
    if kind == "boolean":
        return "boolean"
    if kind == "date":
        return {"type": "int", "logicalType": "date"}
    if kind == "time":
        return {"type": "int", "logicalType": "time-millis"}
    if kind == "timestamp":
        return {"type": "long", "logicalType": "timestamp-millis"}
    if kind == "uuid":
        return {"type": "string", "logicalType": "uuid"}
    if kind == "json":
        return "string"
    if kind == "array":
        if logical_type.item is None:
            raise SchemaError(
                [ValidationError(path="type", message="LogicalType 'array' requer 'item'")]
            )
        return {"type": "array", "items": _avro_type_for_logical(logical_type.item)}
    raise SchemaError([ValidationError(path="type", message=f"LogicalType desconhecido: {kind}")])


def _wrap_nullable(avro_type: AvroType, *, nullable: bool) -> AvroType:
    return ["null", avro_type] if nullable else avro_type


def _field_doc(schema: Schema, table: TableSpec, column: ColumnSpec) -> str | None:
    if column.type == "ref":
        target_table_name = str(column.params["table"])
        target_table = find_table(schema, target_table_name)
        target_pk_column = target_table.primary_key.columns[0]
        return f"FK → {target_table_name}.{target_pk_column}"
    if column.name in table.primary_key.columns:
        return "PK"
    return None


def _avro_field(schema: Schema, table: TableSpec, column: ColumnSpec) -> dict[str, object]:
    logical_type = logical_type_for_column(schema, table, column)
    field: dict[str, object] = {
        "name": column.name,
        "type": _wrap_nullable(
            _avro_type_for_logical(logical_type), nullable=logical_type.nullable
        ),
    }
    if logical_type.nullable:
        field["default"] = None
    doc = _field_doc(schema, table, column)
    if doc is not None:
        field["doc"] = doc
    return field


def avro_schema(schema: Schema, table: str) -> dict[str, object]:
    """Avro Schema (`record`) de uma tabela do schema dataIpsum (DD-02 §F.3.2).

    Sub-entrega prioritária consumida pela trilha E (sink Kafka, DD-02 E.3.3).
    """
    table_spec = find_table(schema, table)
    return {
        "type": "record",
        "name": table_spec.name,
        "namespace": f"dataipsum.{schema.name}",
        "fields": [_avro_field(schema, table_spec, column) for column in table_spec.columns],
    }
