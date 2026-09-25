"""Testes do sink `csv` (DD-02, E.3.1, E.6)."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest
from tests.sinks.conftest import make_column, make_run_context, make_table

from dataipsum.errors import SinkError
from dataipsum.sinks.csv_sink import CsvSink


def _open_and_write(
    sink: CsvSink, tmp_path: Path, table_name: str, schema: pa.Schema, batch: pa.RecordBatch
) -> Path:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    table = make_table(table_name, [make_column(name, "string") for name in schema.names])
    sink.open(make_run_context(str(out_dir)), table, schema)
    sink.write_chunk(1, batch)
    return out_dir / table_name / "part-00001.csv"


def test_header_and_rows(tmp_path: Path) -> None:
    schema = pa.schema([("id", pa.int64()), ("nome", pa.string())])
    batch = pa.record_batch([pa.array([1, 2]), pa.array(["Ana", "Bia"])], schema=schema)
    path = _open_and_write(CsvSink(), tmp_path, "usuarios", schema, batch)

    with path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.reader(csv_file))

    assert rows[0] == ["id", "nome"]
    assert rows[1:] == [["1", "Ana"], ["2", "Bia"]]


@pytest.mark.parametrize(("delimiter", "expected"), [(";", ";"), ("|", "|"), ("\t", "\t")])
def test_delimiter_options(tmp_path: Path, delimiter: str, expected: str) -> None:
    schema = pa.schema([("a", pa.int64()), ("b", pa.int64())])
    batch = pa.record_batch([pa.array([1]), pa.array([2])], schema=schema)
    path = _open_and_write(CsvSink({"delimiter": delimiter}), tmp_path, "t", schema, batch)

    text = path.read_text(encoding="utf-8")
    assert f"1{expected}2" in text


def test_invalid_delimiter_rejected(tmp_path: Path) -> None:
    schema = pa.schema([("a", pa.int64())])
    batch = pa.record_batch([pa.array([1])], schema=schema)
    with pytest.raises(SinkError):
        _open_and_write(CsvSink({"delimiter": "$"}), tmp_path, "t", schema, batch)


def test_null_value_option(tmp_path: Path) -> None:
    schema = pa.schema([("nome", pa.string())])
    batch = pa.record_batch([pa.array([None, "Ana"])], schema=schema)
    path = _open_and_write(CsvSink({"null_value": "NULL"}), tmp_path, "t", schema, batch)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1] == "NULL"
    assert lines[2] == "Ana"


def test_default_null_value_is_empty_string(tmp_path: Path) -> None:
    schema = pa.schema([("nome", pa.string())])
    batch = pa.record_batch([pa.array([None])], schema=schema)
    path = _open_and_write(CsvSink(), tmp_path, "t", schema, batch)

    with path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.reader(csv_file))
    assert rows[1] == [""]


@pytest.mark.parametrize("dangerous_value", ["=cmd", "+1", "-1", "@sum"])
def test_escape_formulas_prefixes_apostrophe(tmp_path: Path, dangerous_value: str) -> None:
    schema = pa.schema([("texto", pa.string())])
    batch = pa.record_batch([pa.array([dangerous_value])], schema=schema)
    path = _open_and_write(CsvSink({"escape_formulas": True}), tmp_path, "t", schema, batch)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1] == f"'{dangerous_value}"


def test_escape_formulas_disabled_by_default(tmp_path: Path) -> None:
    schema = pa.schema([("texto", pa.string())])
    batch = pa.record_batch([pa.array(["=cmd"])], schema=schema)
    path = _open_and_write(CsvSink(), tmp_path, "t", schema, batch)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1] == "=cmd"


def test_decimal_never_uses_scientific_notation(tmp_path: Path) -> None:
    schema = pa.schema([("valor", pa.decimal128(20, 10))])
    batch = pa.record_batch(
        [pa.array([Decimal("0.0000000001")], type=pa.decimal128(20, 10))], schema=schema
    )
    path = _open_and_write(CsvSink(), tmp_path, "t", schema, batch)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1] == "0.0000000001"
    assert "E" not in lines[1] and "e" not in lines[1]


def test_boolean_lowercase(tmp_path: Path) -> None:
    schema = pa.schema([("ativo", pa.bool_())])
    batch = pa.record_batch([pa.array([True, False])], schema=schema)
    path = _open_and_write(CsvSink(), tmp_path, "t", schema, batch)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[1:] == ["true", "false"]


def test_quoting_of_delimiter_and_newline_values(tmp_path: Path) -> None:
    schema = pa.schema([("texto", pa.string())])
    batch = pa.record_batch([pa.array(["a,b\nc"])], schema=schema)
    path = _open_and_write(CsvSink(), tmp_path, "t", schema, batch)

    with path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.reader(csv_file))
    assert rows[1] == ["a,b\nc"]


def test_array_column_as_json_text(tmp_path: Path) -> None:
    schema = pa.schema([("tags", pa.list_(pa.string()))])
    batch = pa.record_batch([pa.array([["a", "b"]])], schema=schema)
    path = _open_and_write(CsvSink(), tmp_path, "t", schema, batch)

    with path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.reader(csv_file))
    assert rows[1] == ['["a", "b"]']


def test_no_utf8_bom(tmp_path: Path) -> None:
    schema = pa.schema([("nome", pa.string())])
    batch = pa.record_batch([pa.array(["Ana"])], schema=schema)
    path = _open_and_write(CsvSink(), tmp_path, "t", schema, batch)

    raw_bytes = path.read_bytes()
    assert not raw_bytes.startswith(b"\xef\xbb\xbf")
