"""`dataipsum schema ...`: validar, exportar, importar e imprimir o JSON Schema
do formato (DD-02 §G.3.1). Só faz parsing, chama `dataipsum.api`/
`dataipsum.config`/`dataipsum.schema.models` e formata a saída.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

import typer
import yaml

from dataipsum import api
from dataipsum.cli._errors import fail, translate_errors
from dataipsum.schema.models import Schema

schema_app = typer.Typer(add_completion=False, help="Operações sobre o schema.")


@schema_app.command("validate")
def validate_cmd(
    schema_path: Annotated[Path, typer.Argument(help="Schema YAML/JSON a validar.")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Resultado em JSON no stdout.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Mostra stack trace em erros.")
    ] = False,
) -> None:
    """Valida um schema e lista os erros com o caminho de cada um."""
    with translate_errors(verbose=verbose, as_json=json_output):
        schema = api.load_schema(schema_path)
        report = api.validate(schema)
        if not report.is_valid:
            message = "; ".join(f"{error.path}: {error.message}" for error in report.errors)
            raise fail(message, as_json=json_output)
        if json_output:
            typer.echo(json.dumps({"status": "ok"}, ensure_ascii=False))
        else:
            typer.echo("schema válido")


@schema_app.command("export")
def export_cmd(
    schema_path: Annotated[Path, typer.Argument(help="Schema YAML/JSON a exportar.")],
    fmt: Annotated[Literal["ddl", "avro"], typer.Option("--format", help="Formato de exportação.")],
    out_dir: Annotated[Path, typer.Option("-o", "--out", help="Diretório de saída.")],
    dialect: Annotated[
        str | None, typer.Option("--dialect", help="Dialeto SQL (obrigatório para --format ddl).")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Mostra stack trace em erros.")
    ] = False,
) -> None:
    """Exporta o schema para DDL SQL ou Avro (trilha F)."""
    with translate_errors(verbose=verbose):
        schema = api.load_schema(schema_path)
        paths = api.export_schema(schema, fmt, dialect, out_dir=out_dir)
        for path in paths:
            typer.echo(str(path))


@schema_app.command("import")
def import_cmd(
    sql_path: Annotated[Path, typer.Argument(help="Arquivo .sql com o DDL a importar.")],
    dialect: Annotated[str, typer.Option("--dialect", help="Dialeto SQL do arquivo.")],
    out: Annotated[Path, typer.Option("-o", "--out", help="Caminho do schema.yaml gerado.")],
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Mostra stack trace em erros.")
    ] = False,
) -> None:
    """Importa um schema a partir de DDL SQL (trilha F, M3)."""
    with translate_errors(verbose=verbose):
        sql_text = sql_path.read_text(encoding="utf-8")
        schema = api.import_ddl(sql_text, dialect)
        out.write_text(
            yaml.safe_dump(
                schema.model_dump(mode="json", exclude_none=True),
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        typer.echo(str(out))


@schema_app.command("jsonschema")
def jsonschema_cmd(
    out: Annotated[
        Path | None, typer.Option("-o", "--out", help="Grava o JSON Schema neste arquivo.")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Mostra stack trace em erros.")
    ] = False,
) -> None:
    """Imprime o JSON Schema versionado do formato de schema do dataIpsum."""
    with translate_errors(verbose=verbose):
        payload = json.dumps(
            Schema.model_json_schema(), indent=2, ensure_ascii=False, sort_keys=True
        )
        if out is not None:
            out.write_text(payload + "\n", encoding="utf-8")
        else:
            typer.echo(payload)
