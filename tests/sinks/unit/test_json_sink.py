"""Testes dos sinks `jsonl`/`json` (DD-02, E.3.1, E.6)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
from tests.sinks.conftest import make_column, make_run_context, make_table

from dataipsum.sinks.json_sink import JsonlSink, JsonSink


def _open_and_write(
    sink: JsonlSink | JsonSink,
    tmp_path: Path,
    table_name: str,
    schema: pa.Schema,
    batch: pa.RecordBatch,
) -> Path:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    table = make_table(table_name, [make_column(name, "string") for name in schema.names])
    sink.open(make_run_context(str(out_dir)), table, schema)
    sink.write_chunk(1, batch)
    extension = "jsonl" if isinstance(sink, JsonlSink) else "json"
    return out_dir / table_name / f"part-00001.{extension}"


def test_jsonl_one_object_per_line(tmp_path: Path) -> None:
    schema = pa.schema([("id", pa.int64()), ("nome", pa.string())])
    batch = pa.record_batch([pa.array([1, 2]), pa.array(["Ana", "Bia"])], schema=schema)
    path = _open_and_write(JsonlSink(), tmp_path, "usuarios", schema, batch)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        {"id": 1, "nome": "Ana"},
        {"id": 2, "nome": "Bia"},
    ]


def test_json_is_a_single_array(tmp_path: Path) -> None:
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1, 2, 3])], schema=schema)
    path = _open_and_write(JsonSink(), tmp_path, "usuarios", schema, batch)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_decimal_as_exact_string(tmp_path: Path) -> None:
    schema = pa.schema([("preco", pa.decimal128(10, 2))])
    batch = pa.record_batch(
        [pa.array([Decimal("19.90")], type=pa.decimal128(10, 2))], schema=schema
    )
    path = _open_and_write(JsonlSink(), tmp_path, "produtos", schema, batch)

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["preco"] == "19.90"
    assert isinstance(row["preco"], str)


def test_array_stays_a_native_list(tmp_path: Path) -> None:
    schema = pa.schema([("tags", pa.list_(pa.string()))])
    batch = pa.record_batch([pa.array([["a", "b"]])], schema=schema)
    path = _open_and_write(JsonlSink(), tmp_path, "t", schema, batch)

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["tags"] == ["a", "b"]


def test_json_logical_column_embedded_as_object(tmp_path: Path) -> None:
    field = pa.field("atributos", pa.string(), metadata={b"dataipsum.logical_kind": b"json"})
    schema = pa.schema([field])
    batch = pa.record_batch([pa.array(['{"cor": "azul"}'])], schema=schema)
    path = _open_and_write(JsonlSink(), tmp_path, "t", schema, batch)

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["atributos"] == {"cor": "azul"}


def test_plain_string_column_is_not_parsed_as_json(tmp_path: Path) -> None:
    schema = pa.schema([("bio", pa.string())])
    batch = pa.record_batch([pa.array(['{"cor": "azul"}'])], schema=schema)
    path = _open_and_write(JsonlSink(), tmp_path, "t", schema, batch)

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["bio"] == '{"cor": "azul"}'


def test_ensure_ascii_false_keeps_unicode(tmp_path: Path) -> None:
    schema = pa.schema([("nome", pa.string())])
    batch = pa.record_batch([pa.array(["Joaquim Ação"])], schema=schema)
    path = _open_and_write(JsonlSink(), tmp_path, "t", schema, batch)

    text = path.read_text(encoding="utf-8")
    assert "Joaquim Ação" in text
    assert "\\u" not in text


def test_null_becomes_json_null(tmp_path: Path) -> None:
    schema = pa.schema([("bio", pa.string())])
    batch = pa.record_batch([pa.array([None])], schema=schema)
    path = _open_and_write(JsonlSink(), tmp_path, "t", schema, batch)

    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["bio"] is None
