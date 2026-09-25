"""Fixtures compartilhadas dos testes unitários da CLI (DD-02 §G.6).

A CLI é testada com a façade fake: `load_schema`/`validate` já são reais (DD-00
S2/S3), então só `generate`, `resume`, `export_schema` e `import_ddl` (ainda
`NotImplementedError`, das trilhas D/F) são substituídos por fakes roteiráveis.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataipsum import api
from dataipsum.api import RunResult
from dataipsum.config import RunOptions


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def make_run_result() -> Callable[..., RunResult]:
    return _make_run_result


def _make_run_result(
    *,
    status: str = "completed",
    pending_chunks: int = 0,
    run_id: str = "run-1",
    tables: dict[str, int] | None = None,
    manifest_path: Path | None = None,
) -> RunResult:
    return RunResult(
        run_id=run_id,
        status=status,
        manifest_path=manifest_path or Path("out/_manifest.json"),
        tables=tables or {"users": 3},
        pending_chunks=pending_chunks,
    )


@pytest.fixture
def captured() -> dict[str, Any]:
    return {}


@pytest.fixture
def fake_facade(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> dict[str, Any]:
    """Substitui `generate`/`resume`/`export_schema`/`import_ddl` por fakes que
    registram os argumentos recebidos em `captured` e devolvem sucesso."""

    def fake_generate(schema: object, options: RunOptions) -> RunResult:
        captured["generate_schema"] = schema
        captured["generate_options"] = options
        return _make_run_result()

    def fake_resume(out_dir: Path, options: RunOptions) -> RunResult:
        captured["resume_out_dir"] = out_dir
        captured["resume_options"] = options
        return _make_run_result()

    def fake_export_schema(
        schema: object, format: str, dialect: str | None = None, *, out_dir: Path
    ) -> list[Path]:
        captured["export_args"] = (schema, format, dialect, out_dir)
        return [out_dir / f"schema.{format}"]

    def fake_import_ddl(sql_text: str, dialect: str) -> object:
        from dataipsum.schema.models import (
            ColumnSpec,
            PrimaryKeySpec,
            Schema,
            TableSpec,
        )

        captured["import_args"] = (sql_text, dialect)
        return Schema(
            version=1,
            tables=[
                TableSpec(
                    name="importada",
                    rows=1,
                    primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
                    columns=[ColumnSpec(name="id", type="int")],
                )
            ],
        )

    monkeypatch.setattr(api, "generate", fake_generate)
    monkeypatch.setattr(api, "resume", fake_resume)
    monkeypatch.setattr(api, "export_schema", fake_export_schema)
    monkeypatch.setattr(api, "import_ddl", fake_import_ddl)
    return captured
