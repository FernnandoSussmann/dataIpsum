"""`dataipsum resume` (DD-02 §G.6): chama `api.resume` com o schema/sink do
manifesto e aceita `--llm-only`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from dataipsum.cli import app

_MANIFEST = {
    "manifest_version": 1,
    "run_id": "abc",
    "dataipsum_version": "0.1.0",
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
    "status": "partial",
    "seed": 1,
    "seed_source": "user",
    "chunk_size": 10000,
    "schema": {
        "version": 1,
        "tables": [
            {
                "name": "users",
                "rows": 10,
                "primary_key": {"columns": ["id"], "strategy": "sequence"},
                "columns": [{"name": "id", "type": "int"}],
            }
        ],
    },
    "schema_sha256": "x",
    "sink": {"kind": "csv", "options": {}},
    "plan": {},
    "chunks": {},
    "llm": {"providers_used": []},
    "emitted_schemas": [],
}


def _write_manifest(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "_manifest.json").write_text(json.dumps(_MANIFEST), encoding="utf-8")


def test_resume_chama_api_resume(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    _write_manifest(out)
    result = runner.invoke(app, ["resume", str(out)])
    assert result.exit_code == 0, result.stderr
    assert fake_facade["resume_out_dir"] == out


def test_resume_aceita_llm_only(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    out = tmp_path / "out"
    _write_manifest(out)
    result = runner.invoke(app, ["resume", str(out), "--llm-only"])
    assert result.exit_code == 0, result.stderr


def test_resume_sem_manifesto_retorna_codigo_1(runner: CliRunner, tmp_path: Path) -> None:
    result = runner.invoke(app, ["resume", str(tmp_path / "out")])
    assert result.exit_code == 1
