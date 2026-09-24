"""Testes de `dataipsum.api` (DD-00 §7.1: api.py).

`load_schema`/`validate` delegam para `dataipsum.schema.loader` (S2), que
ainda não existe neste worktree. Os testes substituem o ponto de costura real
de `dataipsum.api` (`_load_schema`/`_validate`) via `unittest.mock.patch`, em
vez de depender do módulo `dataipsum.schema.loader` de verdade — ver o
docstring de `tests/core/unit/conftest.py`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from dataipsum import api
from dataipsum.config import RunOptions, SinkConfig
from dataipsum.errors import OutputDirError


def _run_options(out_dir: Path) -> RunOptions:
    return RunOptions(out_dir=out_dir, sink=SinkConfig(kind="parquet"))


# --- load_schema / validate: delegação ---------------------------------------


def test_load_schema_delega_ao_loader() -> None:
    sentinel_schema = object()
    with patch("dataipsum.api._load_schema", return_value=sentinel_schema) as mocked:
        result = api.load_schema("schema.yaml")
    mocked.assert_called_once_with("schema.yaml")
    assert result is sentinel_schema


def test_validate_delega_ao_loader() -> None:
    sentinel_report = object()
    sentinel_schema = object()
    with patch("dataipsum.api._validate", return_value=sentinel_report) as mocked:
        result = api.validate(sentinel_schema)
    mocked.assert_called_once_with(sentinel_schema)
    assert result is sentinel_report


# --- plan / export_schema / import_ddl: esqueletos ---------------------------


def test_plan_levanta_notimplementederror_trilha_b(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError, match="trilha B"):
        api.plan(object(), _run_options(tmp_path / "out"))


def test_export_schema_levanta_notimplementederror_trilha_f(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError, match="trilha F"):
        api.export_schema(object(), "ddl", out_dir=tmp_path)


def test_import_ddl_levanta_notimplementederror_trilha_f() -> None:
    with pytest.raises(NotImplementedError, match="trilha F"):
        api.import_ddl("CREATE TABLE x (id INT);", "postgres")


def test_resume_levanta_notimplementederror_trilha_d(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError, match="trilha D"):
        api.resume(tmp_path, _run_options(tmp_path))


# --- generate: guardrail de diretório de saída roda antes do NotImplementedError --


def test_generate_levanta_notimplementederror_trilha_d_com_out_dir_inexistente(
    tmp_path: Path,
) -> None:
    options = _run_options(tmp_path / "novo_out")
    with pytest.raises(NotImplementedError, match="trilha D"):
        api.generate(object(), options)


def test_generate_levanta_notimplementederror_trilha_d_com_out_dir_vazio(tmp_path: Path) -> None:
    options = _run_options(tmp_path)
    with pytest.raises(NotImplementedError, match="trilha D"):
        api.generate(object(), options)


def test_generate_recusa_out_dir_nao_vazio_sem_manifesto(tmp_path: Path) -> None:
    (tmp_path / "arquivo_qualquer.txt").write_text("x", encoding="utf-8")
    options = _run_options(tmp_path)
    with pytest.raises(OutputDirError):
        api.generate(object(), options)
    assert list(tmp_path.iterdir()) == [tmp_path / "arquivo_qualquer.txt"]


def test_generate_recusa_out_dir_com_manifesto_anterior_e_sugere_resume(tmp_path: Path) -> None:
    (tmp_path / "_manifest.json").write_text("{}", encoding="utf-8")
    options = _run_options(tmp_path)
    with pytest.raises(OutputDirError, match=f"resume {tmp_path}"):
        api.generate(object(), options)
    assert (tmp_path / "_manifest.json").read_text(encoding="utf-8") == "{}"
