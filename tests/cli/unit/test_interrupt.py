"""Ctrl+C (DD-02 §G.3.1, §G.6): `KeyboardInterrupt` simulado vira código 1, o
manifesto fica `partial` e a mensagem sugere `dataipsum resume`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dataipsum import api
from dataipsum.cli import app

_INLINE_ARGS = ["--table", "users", "--rows", "3", "--col", "id:int:pk"]


def test_ctrl_c_durante_generate_retorna_1_e_sugere_resume(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_generate(schema: object, options: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(api, "generate", fake_generate)
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out)])

    assert result.exit_code == 1
    assert "Ctrl+C" in result.stderr
    assert f"dataipsum resume {out}" in result.stderr


def test_ctrl_c_grava_manifesto_partial_quando_nenhum_existe(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_generate(schema: object, options: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(api, "generate", fake_generate)
    out = tmp_path / "out"
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out)])

    assert result.exit_code == 1
    manifest_path = out / "_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "partial"


def test_ctrl_c_nao_sobrescreve_manifesto_ja_gravado(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "out"
    out.mkdir(parents=True)
    manifest_path = out / "_manifest.json"
    manifest_path.write_text(json.dumps({"status": "running", "sentinel": True}), encoding="utf-8")

    def fake_generate(schema: object, options: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(api, "generate", fake_generate)
    result = runner.invoke(app, ["gen", *_INLINE_ARGS, "-o", str(out)])

    assert result.exit_code == 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sentinel"] is True
