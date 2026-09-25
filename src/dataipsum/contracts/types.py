"""LogicalType: tipo canônico declarado por cada gerador (DD-00 §3.5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pyarrow as pa

LogicalKind = Literal[
    "string",
    "text",
    "char",
    "int64",
    "int32",
    "float64",
    "decimal",
    "boolean",
    "date",
    "time",
    "timestamp",
    "uuid",
    "json",
    "array",
]


@dataclass(frozen=True)
class LogicalType:
    kind: LogicalKind
    max_length: int | None = None
    length: int | None = None
    precision: int | None = None
    scale: int | None = None
    tz: bool = False
    item: LogicalType | None = None
    max_items: int | None = None
    nullable: bool = False


def string(max_length: int, *, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="string", max_length=max_length, nullable=nullable)


def text(*, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="text", nullable=nullable)


def char(length: int, *, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="char", length=length, nullable=nullable)


def int64(*, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="int64", nullable=nullable)


def int32(*, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="int32", nullable=nullable)


def float64(*, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="float64", nullable=nullable)


def decimal(precision: int, scale: int, *, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="decimal", precision=precision, scale=scale, nullable=nullable)


def boolean(*, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="boolean", nullable=nullable)


def date(*, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="date", nullable=nullable)


def time(*, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="time", nullable=nullable)


def timestamp(*, tz: bool = False, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="timestamp", tz=tz, nullable=nullable)


def uuid(*, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="uuid", nullable=nullable)


def json(*, nullable: bool = False) -> LogicalType:
    return LogicalType(kind="json", nullable=nullable)


def array(
    item: LogicalType, max_items: int | None = None, *, nullable: bool = False
) -> LogicalType:
    return LogicalType(kind="array", item=item, max_items=max_items, nullable=nullable)


# DD-00 §3.5 cita "time32[s|ms]" para o mapeamento de `time`; fixamos "ms" (o
# schema não tem campo de precisão por coluna hoje). Revisar se uma trilha
# precisar de resolução de segundo.
_ARROW_TIME_UNIT_FOR_TIME = "ms"


def to_arrow_type(logical_type: LogicalType) -> pa.DataType:
    """Mapeamento único LogicalType -> pyarrow.DataType, usado pelo motor e pelos sinks."""
    kind = logical_type.kind
    if kind in ("string", "text"):
        return pa.string()
    if kind == "char":
        return pa.string()
    if kind == "int64":
        return pa.int64()
    if kind == "int32":
        return pa.int32()
    if kind == "float64":
        return pa.float64()
    if kind == "decimal":
        precision = logical_type.precision or 10
        scale = logical_type.scale or 2
        return pa.decimal128(precision, scale)
    if kind == "boolean":
        return pa.bool_()
    if kind == "date":
        return pa.date32()
    if kind == "time":
        return pa.time32(_ARROW_TIME_UNIT_FOR_TIME)
    if kind == "timestamp":
        return pa.timestamp("ms", tz="UTC" if logical_type.tz else None)
    if kind == "uuid":
        return pa.string()
    if kind == "json":
        return pa.string()
    if kind == "array":
        if logical_type.item is None:
            raise ValueError("LogicalType 'array' requer 'item'")
        return pa.list_(to_arrow_type(logical_type.item))
    raise ValueError(f"LogicalType desconhecido: {kind}")
