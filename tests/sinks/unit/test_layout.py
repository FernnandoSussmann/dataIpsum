"""Testes de layout/atomicidade dos sinks de arquivo (DD-02, E.6)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dataipsum.errors import SinkError
from dataipsum.sinks._layout import (
    cleanup_orphan_temp_files,
    part_filename,
    table_dir_for,
    validate_table_name,
    write_bytes_atomically,
)


def test_part_filename_pads_to_five_digits() -> None:
    assert part_filename(1, "csv") == "part-00001.csv"
    assert part_filename(42, "parquet") == "part-00042.parquet"


def test_part_filename_widens_beyond_five_digits() -> None:
    assert part_filename(100_000, "csv") == "part-100000.csv"
    assert part_filename(999_999, "csv") == "part-999999.csv"


def test_part_filename_rejects_non_positive_id() -> None:
    with pytest.raises(SinkError):
        part_filename(0, "csv")


def test_validate_table_name_rejects_invalid_identifier() -> None:
    with pytest.raises(SinkError):
        validate_table_name("Usuarios")
    with pytest.raises(SinkError):
        validate_table_name("../etc")


def test_write_bytes_atomically_computes_sha256(tmp_path: Path) -> None:
    table_dir = table_dir_for(tmp_path, "usuarios")
    payload = b"linha,1\n"

    digest = write_bytes_atomically(
        table_dir, "part-00001.csv", lambda path: path.write_bytes(payload)
    )

    final_path = table_dir / "part-00001.csv"
    assert final_path.read_bytes() == payload
    assert digest == hashlib.sha256(payload).hexdigest()
    assert not list(table_dir.glob(".*"))


def test_write_bytes_atomically_leaves_no_final_file_on_failure(tmp_path: Path) -> None:
    table_dir = table_dir_for(tmp_path, "usuarios")

    def _boom(path: Path) -> None:
        path.write_bytes(b"parcial")
        raise OSError("falha simulada antes do replace")

    with pytest.raises(SinkError):
        write_bytes_atomically(table_dir, "part-00002.parquet", _boom)

    assert not (table_dir / "part-00002.parquet").exists()
    assert list(table_dir.iterdir()) == []


def test_write_bytes_atomically_rewrite_replaces_content(tmp_path: Path) -> None:
    table_dir = table_dir_for(tmp_path, "usuarios")
    write_bytes_atomically(table_dir, "part-00001.csv", lambda path: path.write_bytes(b"v1"))
    write_bytes_atomically(table_dir, "part-00001.csv", lambda path: path.write_bytes(b"v2"))

    assert (table_dir / "part-00001.csv").read_bytes() == b"v2"


def test_cleanup_removes_only_exact_temp_pattern(tmp_path: Path) -> None:
    table_dir = table_dir_for(tmp_path, "usuarios")
    orphan = table_dir / ".part-00001.csv.tmp-11111111-1111-1111-1111-111111111111"
    orphan.write_text("lixo")
    lookalike_1 = table_dir / ".part-00001.csv.tmp-nao-e-uuid"
    lookalike_1.write_text("mantido")
    lookalike_2 = table_dir / "part-00001.csv.tmp-11111111-1111-1111-1111-111111111111"
    lookalike_2.write_text("mantido")
    real_file = table_dir / "part-00001.csv"
    real_file.write_text("dado real")

    cleanup_orphan_temp_files(table_dir)

    assert not orphan.exists()
    assert lookalike_1.exists()
    assert lookalike_2.exists()
    assert real_file.exists()
