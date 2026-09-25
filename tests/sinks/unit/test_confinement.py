"""Testes de confinamento de caminho dos sinks de arquivo (DD-02, E.5.1, E.6)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest
from tests.sinks.conftest import make_column, make_run_context, make_table

from dataipsum.errors import OutputDirError, SinkError
from dataipsum.sinks.csv_sink import CsvSink


def test_symlink_table_dir_is_rejected(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    outside_target = tmp_path / "fora"
    outside_target.mkdir()
    (out_dir / "usuarios").symlink_to(outside_target, target_is_directory=True)

    table = make_table("usuarios", [make_column("id", "int64")])
    sink = CsvSink()

    with pytest.raises(OutputDirError):
        sink.open(make_run_context(str(out_dir)), table, pa.schema([("id", pa.int64())]))


def test_invalid_table_name_never_reaches_sink_write(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    table = make_table("valido", [make_column("id", "int64")])
    invalid_table = table.model_copy(update={"name": "Invalido"})

    sink = CsvSink()
    with pytest.raises(SinkError):
        sink.open(make_run_context(str(out_dir)), invalid_table, pa.schema([("id", pa.int64())]))
