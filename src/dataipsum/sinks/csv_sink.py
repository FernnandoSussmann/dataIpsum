"""Sink `csv` (DD-02, trilha E, M1, E.3.1): UTF-8 sem BOM, RFC 4180, aspas mínimas."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import ClassVar

import pyarrow as pa

from dataipsum.errors import SinkError
from dataipsum.sinks._file_sink_base import FileSinkBase
from dataipsum.sinks._values import csv_cell_text

_VALID_DELIMITERS = {",": ",", ";": ";", "tab": "\t", "\t": "\t", "|": "|"}
_DEFAULT_DELIMITER = ","
_DEFAULT_NULL_VALUE = ""


def _resolve_delimiter(value: object) -> str:
    text = str(value)
    if text not in _VALID_DELIMITERS:
        raise SinkError(
            f"'delimiter' inválido: {text!r}. Aceitos: ',', ';', '\\t' (ou 'tab') e '|'"
        )
    return _VALID_DELIMITERS[text]


class CsvSink(FileSinkBase):
    extension: ClassVar[str] = "csv"

    def _write_body(self, tmp_path: Path, batch: pa.RecordBatch) -> None:
        delimiter = _resolve_delimiter(self.options.get("delimiter", _DEFAULT_DELIMITER))
        null_value = str(self.options.get("null_value", _DEFAULT_NULL_VALUE))
        escape_formulas = bool(self.options.get("escape_formulas", False))
        column_names = batch.schema.names
        string_columns = frozenset(
            field.name for field in batch.schema if pa.types.is_string(field.type)
        )
        rows = batch.to_pylist()
        with tmp_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(column_names)
            for row in rows:
                writer.writerow(
                    [
                        csv_cell_text(
                            row[name],
                            null_value=null_value,
                            escape_formulas=escape_formulas and name in string_columns,
                        )
                        for name in column_names
                    ]
                )
