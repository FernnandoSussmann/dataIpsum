"""Testes do sink `parquet` (DD-02, E.3.1, E.6): round-trip de LogicalTypes e
compressão."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from tests.sinks.conftest import make_column, make_run_context, make_table

from dataipsum.errors import SinkError
from dataipsum.sinks.parquet_sink import ParquetSink


def _open_and_write(
    sink: ParquetSink, tmp_path: Path, table_name: str, schema: pa.Schema, batch: pa.RecordBatch
) -> Path:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    table = make_table(table_name, [make_column(name, "string") for name in schema.names])
    sink.open(make_run_context(str(out_dir)), table, schema)
    sink.write_chunk(1, batch)
    return out_dir / table_name / "part-00001.parquet"


def test_round_trip_all_logical_types(tmp_path: Path) -> None:
    schema = pa.schema(
        [
            ("preco", pa.decimal128(10, 2)),
            ("criado_em", pa.timestamp("ms")),
            ("nascimento", pa.date32()),
            ("hora", pa.time32("ms")),
            ("id", pa.string()),
            ("atributos", pa.string()),
            ("tags", pa.list_(pa.string())),
            ("bio", pa.string()),
        ]
    )
    fixed_uuid = str(uuid.uuid4())
    batch = pa.record_batch(
        [
            pa.array([Decimal("123.45"), None], type=pa.decimal128(10, 2)),
            pa.array(
                [datetime.datetime(2024, 1, 1, 12, 0, 0), None],
                type=pa.timestamp("ms"),
            ),
            pa.array([datetime.date(2024, 1, 1), None], type=pa.date32()),
            pa.array([datetime.time(10, 30), None], type=pa.time32("ms")),
            pa.array([fixed_uuid, None]),
            pa.array(['{"cor": "azul"}', None]),
            pa.array([["a", "b"], None]),
            pa.array(["texto", None]),
        ],
        schema=schema,
    )

    path = _open_and_write(ParquetSink(), tmp_path, "usuarios", schema, batch)
    table = pq.read_table(path)

    assert table.column("preco").to_pylist() == [Decimal("123.45"), None]
    assert table.column("criado_em").to_pylist() == [
        datetime.datetime(2024, 1, 1, 12, 0, 0),
        None,
    ]
    assert table.column("nascimento").to_pylist() == [datetime.date(2024, 1, 1), None]
    assert table.column("hora").to_pylist() == [datetime.time(10, 30), None]
    assert table.column("id").to_pylist() == [fixed_uuid, None]
    assert table.column("tags").to_pylist() == [["a", "b"], None]
    assert table.num_rows == 2


def test_single_row_group_per_chunk(tmp_path: Path) -> None:
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array(list(range(500)))], schema=schema)
    path = _open_and_write(ParquetSink(), tmp_path, "t", schema, batch)

    parquet_file = pq.ParquetFile(path)
    assert parquet_file.num_row_groups == 1


@pytest.mark.parametrize("compression", ["zstd", "snappy", "gzip", "none"])
def test_supported_compressions(tmp_path: Path, compression: str) -> None:
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1, 2, 3])], schema=schema)
    path = _open_and_write(ParquetSink({"compression": compression}), tmp_path, "t", schema, batch)

    assert pq.read_table(path).column("id").to_pylist() == [1, 2, 3]


def test_invalid_compression_rejected(tmp_path: Path) -> None:
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1])], schema=schema)
    with pytest.raises(SinkError):
        _open_and_write(ParquetSink({"compression": "bzip2"}), tmp_path, "t", schema, batch)
