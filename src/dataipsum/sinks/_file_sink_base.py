"""Base comum aos sinks de arquivo (`csv`, `json`, `jsonl`, `parquet`), DD-02 E.3.1.

Cada sink concreto só implementa `_write_body` (produz o conteúdo no caminho
temporário) e declara `extension`. O resto (layout, limpeza, escrita atômica,
`chunk_state`) é compartilhado.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar, cast

import pyarrow as pa

from dataipsum.contracts.sink import ChunkState, RunContext, SinkCapabilities, SinkReceipt
from dataipsum.errors import SinkError
from dataipsum.schema.models import TableSpec
from dataipsum.sinks._layout import (
    cleanup_orphan_temp_files,
    part_filename,
    table_dir_for,
    write_bytes_atomically,
)

FILE_SINK_CAPABILITIES = SinkCapabilities(
    atomic_chunk=True, replace_chunk=True, referential_integrity=False
)


class FileSinkBase:
    """Sink de arquivo: um `part-<id>.<ext>` por chunk, escrito atomicamente (E.3.1)."""

    extension: ClassVar[str]
    capabilities: ClassVar[SinkCapabilities] = FILE_SINK_CAPABILITIES

    def __init__(self, options: Mapping[str, object] | None = None) -> None:
        self.options: Mapping[str, object] = dict(options or {})
        self._table_dir: Path | None = None
        self._arrow_schema: pa.Schema | None = None

    def open(self, run: RunContext, table: object, arrow_schema: pa.Schema) -> None:
        table_spec = cast(TableSpec, table)
        table_dir = table_dir_for(Path(run.out_dir), table_spec.name)
        cleanup_orphan_temp_files(table_dir)
        self._table_dir = table_dir
        self._arrow_schema = arrow_schema

    def write_chunk(self, chunk_id: int, batch: pa.RecordBatch | object) -> SinkReceipt:
        table_dir = self._require_table_dir()
        record_batch = cast(pa.RecordBatch, batch)
        final_name = part_filename(chunk_id, self.extension)
        digest = write_bytes_atomically(
            table_dir, final_name, lambda tmp_path: self._write_body(tmp_path, record_batch)
        )
        return SinkReceipt(sink_ref=str(table_dir / final_name), sha256=digest)

    def chunk_state(self, chunk_id: int) -> ChunkState:
        table_dir = self._require_table_dir()
        final_path = table_dir / part_filename(chunk_id, self.extension)
        return "committed" if final_path.exists() else "absent"

    def close(self) -> None:
        self._table_dir = None
        self._arrow_schema = None

    def _require_table_dir(self) -> Path:
        if self._table_dir is None:
            raise SinkError("sink não foi aberto: chame open() antes de write_chunk/chunk_state")
        return self._table_dir

    def _write_body(self, tmp_path: Path, batch: pa.RecordBatch) -> None:
        raise NotImplementedError
