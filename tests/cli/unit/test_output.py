"""Disciplina de stdout/stderr (DD-02 §G.3.1, §G.6): stdout limpo sem `--json`,
`--json` é JSON válido no stdout, e logs de progresso vão para o stderr."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from dataipsum.cli import app

_INLINE_ARGS = ["--table", "users", "--rows", "3", "--col", "id:int:pk"]


def test_stdout_limpo_sem_json(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""


def test_json_e_json_valido_no_stdout(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out), "--json"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "completed"
    assert payload["run_id"] == "run-1"


def test_progresso_vai_para_stderr(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out)])
    assert result.exit_code == 0
    assert "iniciando geração" in result.stderr


def test_quiet_silencia_o_progresso(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out), "-q"])
    assert result.exit_code == 0
    assert "iniciando geração" not in result.stderr


def test_json_em_erro_e_json_valido_com_status_error(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", "-o", str(out), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert "error" in payload
