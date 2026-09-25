"""`dataipsum gen` (DD-02 §G.6): opções -> `RunOptions`, precedência, validação
e códigos de saída."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataipsum.api import RunResult
from dataipsum.cli import app

_INLINE_ARGS = ["--table", "users", "--rows", "3", "--col", "id:int:pk", "--col", "nome:string"]


def test_opcoes_chegam_em_run_options_com_o_valor_certo(
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
            "--seed",
            "42",
            "--chunk-size",
            "500",
            "--max-rows",
            "1000",
            "--format",
            "csv",
            "--cpu-max",
            "80",
            "--mem-max",
            "50",
        ],
    )
    assert result.exit_code == 0, result.stderr
    options = fake_facade["generate_options"]
    assert options.out_dir == out
    assert options.seed == 42
    assert options.chunk_size == 500
    assert options.max_rows == 1000
    assert options.sink.kind == "csv"
    assert options.cpu_max == 80.0
    assert options.mem_max == 50.0


def test_precedencia_cli_sobre_env(
    runner: CliRunner,
    fake_facade: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATAIPSUM_SEED", "999")
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out), "--seed", "1"])
    assert result.exit_code == 0, result.stderr
    assert fake_facade["generate_options"].seed == 1


def test_precedencia_env_sobre_padrao(
    runner: CliRunner,
    fake_facade: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATAIPSUM_SEED", "777")
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out)])
    assert result.exit_code == 0, result.stderr
    assert fake_facade["generate_options"].seed == 777


def test_format_desconhecido_retorna_codigo_1(runner: CliRunner, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out), "--format", "xml"])
    assert result.exit_code == 1


def test_schema_invalido_retorna_codigo_1_com_caminho_do_erro(
    runner: CliRunner, tmp_path: Path
) -> None:
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(
        """
version: 1
tables:
  - name: usuarios
    rows: 10
    primary_key: {columns: [id], strategy: sequence}
    columns:
      - {name: id, type: int}
      - {name: cpf, type: cpf, invalid_ratio: 2}
""",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["gen", str(schema_path), "-o", str(tmp_path / "out")])
    assert result.exit_code == 1
    assert "tables[0].columns[1].invalid_ratio" in result.stderr


def test_execucao_partial_retorna_codigo_1(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    make_run_result: Callable[..., RunResult],
) -> None:
    from dataipsum import api

    monkeypatch.setattr(
        api,
        "generate",
        lambda schema, options: make_run_result(status="partial", pending_chunks=2),
    )
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out)])
    assert result.exit_code == 1
    assert "resume" in result.stderr


def test_execucao_com_falha_retorna_codigo_1(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataipsum import api
    from dataipsum.errors import ExecutorError

    def fake_generate(schema: object, options: object) -> None:
        raise ExecutorError("falha simulada no executor")

    monkeypatch.setattr(api, "generate", fake_generate)
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out)])
    assert result.exit_code == 1
    assert "falha simulada" in result.stderr


def test_sucesso_retorna_codigo_0(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out)])
    assert result.exit_code == 0


def test_erro_de_uso_do_click_vira_codigo_1(runner: CliRunner) -> None:
    result = runner.invoke(app, ["gen", "--esta-opcao-nao-existe"])
    assert result.exit_code == 1


def test_opcao_obrigatoria_ausente_vira_codigo_1(runner: CliRunner) -> None:
    result = runner.invoke(app, ["gen", *_INLINE_ARGS])  # sem -o/--out
    assert result.exit_code == 1
