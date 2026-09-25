"""CLI completa da trilha G (DD-02 §G.3.1). Substitui o esqueleto do S1
(DD-00 §3.12.4): `--version`/`--help` continuam funcionando, e `generate` virou
o comando `gen`, real, que hoje ainda depende da trilha D (façade em stub)."""

from __future__ import annotations

from pathlib import Path

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


def test_gen_sem_facade_pronta_falha_com_codigo_1_sem_traceback(tmp_path: Path) -> None:
    """`api.generate` ainda é `NotImplementedError("trilha D")` (DD-00 §3.8): a CLI
    converte isso em código de saída 1, sem deixar a exceção propagar crua."""
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "gen",
            "--table",
            "users",
            "--rows",
            "3",
            "--col",
            "id:int:pk",
            "-o",
            str(out),
        ],
    )
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "trilha D" in result.stderr
