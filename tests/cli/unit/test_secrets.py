"""Guardrail de segredos (DD-02 §G.5.1, §G.6, DD-00 §6.5): `--sink-opt` recusa
chaves que parecem segredo, exceto quando terminam em `_env`, e o valor nunca
aparece na saída."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from dataipsum.cli import app

_INLINE_ARGS = ["--table", "users", "--rows", "3", "--col", "id:int:pk"]


def test_sink_opt_password_e_recusado(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "gen",
            *_INLINE_ARGS,
            "-o",
            str(out),
            "--format",
            "postgres",
            "--sink-opt",
            "password=segredo123",
        ],
    )
    assert result.exit_code == 1
    assert "password_env" in result.stderr
    assert "segredo123" not in result.stdout
    assert "segredo123" not in result.stderr


def test_sink_opt_password_env_e_aceito(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "gen",
            *_INLINE_ARGS,
            "-o",
            str(out),
            "--format",
            "postgres",
            "--sink-opt",
            "password_env=PG_PASS",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert fake_facade["generate_options"].sink.options == {"password_env": "PG_PASS"}


def test_sink_opt_api_key_e_recusado(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out), "--sink-opt", "api_key=abc"])
    assert result.exit_code == 1
    assert "abc" not in result.stdout
