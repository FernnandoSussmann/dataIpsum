"""`dataipsum schema ...` (DD-02 §G.6): cada subcomando chama a função certa da
façade e grava no caminho indicado."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from dataipsum.cli import app

_VALID_SCHEMA = """
version: 1
tables:
  - name: usuarios
    rows: 10
    primary_key: {columns: [id], strategy: sequence}
    columns:
      - {name: id, type: int}
"""


def test_validate_schema_valido_retorna_0(runner: CliRunner, tmp_path: Path) -> None:
    schema_path = tmp_path / "s.yaml"
    schema_path.write_text(_VALID_SCHEMA, encoding="utf-8")
    result = runner.invoke(app, ["schema", "validate", str(schema_path)])
    assert result.exit_code == 0, result.stderr


def test_validate_schema_invalido_retorna_1_com_caminho(runner: CliRunner, tmp_path: Path) -> None:
    schema_path = tmp_path / "s.yaml"
    invalid_schema = _VALID_SCHEMA.replace("type: int}", "type: int, invalid_ratio: 2}")
    schema_path.write_text(invalid_schema, encoding="utf-8")
    result = runner.invoke(app, ["schema", "validate", str(schema_path)])
    assert result.exit_code == 1
    assert "invalid_ratio" in result.stderr


def test_export_chama_api_export_schema(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    schema_path = tmp_path / "s.yaml"
    schema_path.write_text(_VALID_SCHEMA, encoding="utf-8")
    out_dir = tmp_path / "export"
    result = runner.invoke(
        app,
        [
            "schema",
            "export",
            str(schema_path),
            "--format",
            "ddl",
            "--dialect",
            "postgres",
            "-o",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.stderr
    _, fmt, dialect, out = fake_facade["export_args"]
    assert fmt == "ddl"
    assert dialect == "postgres"
    assert out == out_dir
    assert str(out_dir / "schema.ddl") in result.stdout


def test_import_chama_api_import_ddl_e_grava_yaml(
    runner: CliRunner, fake_facade: dict[str, Any], tmp_path: Path
) -> None:
    sql_path = tmp_path / "ddl.sql"
    sql_path.write_text("CREATE TABLE t (id INT);", encoding="utf-8")
    out_path = tmp_path / "schema.yaml"
    result = runner.invoke(
        app, ["schema", "import", str(sql_path), "--dialect", "postgres", "-o", str(out_path)]
    )
    assert result.exit_code == 0, result.stderr
    sql_text, dialect = fake_facade["import_args"]
    assert "CREATE TABLE" in sql_text
    assert dialect == "postgres"
    assert out_path.exists()
    assert "importada" in out_path.read_text(encoding="utf-8")


def test_jsonschema_imprime_json_valido(runner: CliRunner) -> None:
    result = runner.invoke(app, ["schema", "jsonschema"])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["title"] == "Schema"


def test_jsonschema_grava_em_arquivo(runner: CliRunner, tmp_path: Path) -> None:
    out_path = tmp_path / "schema.json"
    result = runner.invoke(app, ["schema", "jsonschema", "-o", str(out_path)])
    assert result.exit_code == 0, result.stderr
    assert json.loads(out_path.read_text(encoding="utf-8"))["title"] == "Schema"
