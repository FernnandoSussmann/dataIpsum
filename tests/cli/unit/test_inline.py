"""Flags inline `--col` (DD-02 §G.6): gramática válida/inválida, `--print-schema`
e a recusa de relações (tipo `ref`)."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from dataipsum.cli import app


def test_print_schema_gera_yaml_equivalente_e_valido(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "gen",
            "--table",
            "users",
            "--rows",
            "10",
            "--col",
            "id:int:pk",
            "--col",
            "nome:nome_proprio:max_length=50",
            "-o",
            str(tmp_path / "out"),
            "--print-schema",
        ],
    )
    assert result.exit_code == 0, result.stderr
    parsed = yaml.safe_load(result.stdout)
    assert parsed["tables"][0]["name"] == "users"
    assert parsed["tables"][0]["rows"] == 10
    assert [c["name"] for c in parsed["tables"][0]["columns"]] == ["id", "nome"]


def test_gramatica_invalida_retorna_codigo_1(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "gen",
            "--table",
            "users",
            "--rows",
            "10",
            "--col",
            "sem-tipo",
            "-o",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 1


def test_relacao_inline_retorna_erro_explicativo(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "gen",
            "--table",
            "pedidos",
            "--rows",
            "10",
            "--col",
            "id:int:pk",
            "--col",
            "usuario_id:ref",
            "-o",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 1
    assert "YAML" in result.stderr


def test_schema_e_inline_juntos_e_erro(runner: CliRunner, tmp_path: Path) -> None:
    schema_path = tmp_path / "s.yaml"
    schema_path.write_text(
        "version: 1\ntables:\n"
        "- name: t\n  rows: 1\n  primary_key: {columns: [id], strategy: sequence}\n"
        "  columns:\n  - {name: id, type: int}\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["gen", str(schema_path), "--table", "users", "--rows", "1", "-o", str(tmp_path / "out")],
    )
    assert result.exit_code == 1


def test_faltando_schema_e_flags_inline_e_erro(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(app, ["gen", "-o", str(tmp_path / "out")])
    assert result.exit_code == 1
