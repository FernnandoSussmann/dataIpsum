"""`export_schema`: escrita atômica e confinada do DDL/Avro exportados (DD-02 §F.3.3)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Literal

from dataipsum.errors import SchemaError, ValidationError
from dataipsum.manifest import confine_to_output_dir
from dataipsum.schema.models import Schema
from dataipsum.schema_io.avro_export import avro_schema
from dataipsum.schema_io.ddl_export import ddl_for

SchemaFormat = Literal["ddl", "avro"]


def _write_atomic(out_dir: Path, final_path: Path, content: str) -> Path:
    """Grava `content` em `final_path` atomicamente (mesmo padrão de `manifest.py` §3.7)."""
    confined_final = confine_to_output_dir(out_dir, final_path)
    tmp_path = confine_to_output_dir(
        out_dir, out_dir / f".{final_path.name}.tmp-{uuid.uuid4().hex}"
    )
    with tmp_path.open("w", encoding="utf-8") as tmp_file:
        tmp_file.write(content)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
    os.replace(tmp_path, confined_final)
    dir_fd = os.open(out_dir, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return confined_final


def _export_ddl(schema: Schema, dialect: str | None, out_dir: Path) -> list[Path]:
    if dialect is None:
        raise SchemaError(
            [ValidationError(path="dialect", message="export de DDL exige 'dialect'")]
        )
    return [_write_atomic(out_dir, out_dir / f"{dialect}.sql", ddl_for(schema, dialect))]


def _export_avro(schema: Schema, out_dir: Path) -> list[Path]:
    return [
        _write_atomic(
            out_dir,
            out_dir / f"{table.name}.avsc",
            json.dumps(avro_schema(schema, table.name), indent=2, ensure_ascii=False) + "\n",
        )
        for table in schema.tables
    ]


def export_schema(
    schema: Schema, format: SchemaFormat, dialect: str | None = None, *, out_dir: Path
) -> list[Path]:
    """Exporta o schema para DDL ou Avro em `out_dir` (DD-02 §F.3.3, §F.4).

    Implementação real de `dataipsum.api.export_schema`. Os arquivos são gravados
    atomicamente e confinados a `out_dir` (DD-00 §6.4), reaproveitando o mesmo
    padrão de `manifest.write_manifest_atomic`.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if format == "ddl":
        return _export_ddl(schema, dialect, out_dir)
    if format == "avro":
        return _export_avro(schema, out_dir)
    raise SchemaError(
        [ValidationError(path="format", message=f"formato de export desconhecido: '{format}'")]
    )
