"""Testes de `chunk_state`/ciclo de vida comuns aos sinks de arquivo (DD-02, E.6)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
from tests.sinks.conftest import make_column, make_run_context, make_table

from dataipsum.sinks.csv_sink import CsvSink


def test_chunk_state_absent_then_committed(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    schema = pa.schema([("id", pa.int64())])
    table = make_table("usuarios", [make_column("id", "int64")])
    sink = CsvSink()
    sink.open(make_run_context(str(out_dir)), table, schema)

    assert sink.chunk_state(1) == "absent"

    sink.write_chunk(1, pa.record_batch([pa.array([1])], schema=schema))

    assert sink.chunk_state(1) == "committed"
    assert sink.chunk_state(2) == "absent"


def test_capabilities_declared_for_file_sinks() -> None:
    sink = CsvSink()
    assert sink.capabilities.atomic_chunk is True
    assert sink.capabilities.replace_chunk is True
    assert sink.capabilities.referential_integrity is False
