"""Conversão de valores para os sinks de texto (`csv`, `json`, `jsonl`), DD-02 E.3.1.

`pyarrow.RecordBatch.to_pylist()` já converte cada tipo Arrow para o objeto Python
equivalente (decimal128 -> `decimal.Decimal`, timestamp -> `datetime.datetime`,
date32 -> `datetime.date`, time32 -> `datetime.time`, listas -> `list`). Este módulo
só formata esses objetos Python de acordo com a regra de cada formato (E.3.1).

Ambiguidade conhecida (registrada para o encaixe do S5): o Arrow não distingue
`LogicalType` `json` de `string` comum (`to_arrow_type` mapeia ambos para
`pyarrow.string()`, DD-00 §3.5). Para que `jsonl`/`json` "embutam" uma coluna `json`
como objeto (E.3.1), este módulo procura o metadado de campo
`dataipsum.logical_kind = b"json"`. Sem esse metadado, a coluna é tratada como texto
comum. Quem monta o `arrow_schema` real (motor, DD-01) precisa anexar esse metadado
às colunas `json` para que o comportamento completo se aplique; sem ele, o dado ainda
sai correto, só não é reidratado como objeto aninhado.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pyarrow as pa

FORMULA_PREFIXES = frozenset({"=", "+", "-", "@"})

LOGICAL_KIND_METADATA_KEY = b"dataipsum.logical_kind"
LOGICAL_KIND_JSON = b"json"


def is_json_logical_column(field: pa.Field) -> bool:
    metadata = field.metadata or {}
    return metadata.get(LOGICAL_KIND_METADATA_KEY) == LOGICAL_KIND_JSON


def json_safe(value: object) -> object:
    """Converte recursivamente valores Python (de `to_pylist()`) para algo que
    `json.dumps` aceita nativamente: decimal e datas/horas viram texto ISO-8601 (ou,
    no caso de `Decimal`, texto sem notação científica, E.3.1)."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    return value


def json_cell_value(value: object, *, is_json_text: bool) -> object:
    """Valor pronto para `json.dumps` num objeto `jsonl`/`json` (E.3.1): uma coluna
    `json` (texto contendo JSON) é desserializada e embutida como objeto; as demais
    seguem `json_safe`."""
    if value is None:
        return None
    if is_json_text and isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return json_safe(value)


def csv_cell_text(value: object, *, null_value: str, escape_formulas: bool) -> str:
    """Formata uma célula CSV (E.3.1): booleanos em `true`/`false`, decimal sem
    notação científica, datas/horas em ISO-8601, listas como texto JSON."""
    if value is None:
        return null_value
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, Decimal):
        text = format(value, "f")
    elif isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        text = value.isoformat()
    elif isinstance(value, list):
        text = json.dumps(json_safe(value), ensure_ascii=False)
    else:
        text = str(value)
    if escape_formulas and text[:1] in FORMULA_PREFIXES:
        return f"'{text}"
    return text
