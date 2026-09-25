"""Sink `parquet` (DD-02, trilha E, M1, E.3.1): um row group por chunk, tipos Arrow
do `LogicalType` (DD-00 §3.5), compressão configurável."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq

from dataipsum.errors import SinkError
from dataipsum.sinks._file_sink_base import FileSinkBase

_VALID_COMPRESSIONS = frozenset({"zstd", "snappy", "gzip", "none"})
_DEFAULT_COMPRESSION = "zstd"


class ParquetSink(FileSinkBase):
    extension: ClassVar[str] = "parquet"

    def _write_body(self, tmp_path: Path, batch: pa.RecordBatch) -> None:
        compression_option = str(self.options.get("compression", _DEFAULT_COMPRESSION))
        if compression_option not in _VALID_COMPRESSIONS:
            raise SinkError(
                f"'compression' inválida: {compression_option!r}. "
                f"Aceitas: {sorted(_VALID_COMPRESSIONS)}"
            )
        compression = None if compression_option == "none" else compression_option
        table = pa.Table.from_batches([batch])
        pq.write_table(
            table,
            tmp_path,
            compression=compression,
            row_group_size=max(batch.num_rows, 1),
        )
