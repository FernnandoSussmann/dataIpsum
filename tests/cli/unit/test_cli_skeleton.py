"""Esqueleto de CLI do S1 (DD-00 §3.12.4, critério de aceitação 4)."""

from __future__ import annotations

from typer.testing import CliRunner

from dataipsum.cli import app

runner = CliRunner()


def test_help_executa() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_version_imprime_a_versao_do_pacote() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_gen_levanta_not_implemented() -> None:
    result = runner.invoke(app, ["gen"])
    assert result.exit_code != 0
    assert isinstance(result.exception, NotImplementedError)
