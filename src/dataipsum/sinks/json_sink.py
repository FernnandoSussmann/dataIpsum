"""Sinks `json` e `jsonl` (DD-02, trilha E, M1, E.3.1).

`jsonl`: um objeto JSON por linha. `json`: um array JSON por arquivo. Ambos com
`ensure_ascii=False`, decimal como string e uuid como string canônica (já entregue
assim pelo Arrow, sem conversão extra).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import pyarrow as pa

from dataipsum.sinks._file_sink_base import FileSinkBase
from dataipsum.sinks._values import is_json_logical_column, json_cell_value


def _build_rows(batch: pa.RecordBatch) -> list[dict[str, object]]:
    json_text_columns = frozenset(
        field.name for field in batch.schema if is_json_logical_column(field)
    )
    column_names = batch.schema.names
    return [
        {
            name: json_cell_value(row[name], is_json_text=name in json_text_columns)
            for name in column_names
        }
        for row in batch.to_pylist()
    ]


class JsonlSink(FileSinkBase):
    extension: ClassVar[str] = "jsonl"

    def _write_body(self, tmp_path: Path, batch: pa.RecordBatch) -> None:
        with tmp_path.open("w", encoding="utf-8") as jsonl_file:
            for row in _build_rows(batch):
                jsonl_file.write(json.dumps(row, ensure_ascii=False))
                jsonl_file.write("\n")


class JsonSink(FileSinkBase):
    extension: ClassVar[str] = "json"

    def _write_body(self, tmp_path: Path, batch: pa.RecordBatch) -> None:
        rows = _build_rows(batch)
        with tmp_path.open("w", encoding="utf-8") as json_file:
            json.dump(rows, json_file, ensure_ascii=False)
