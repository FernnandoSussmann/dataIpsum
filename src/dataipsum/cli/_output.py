"""Formatação da saída de `gen`/`resume`: stdout limpo, `--json` para máquinas
e progresso/erros no stderr (DD-02 §G.3.1)."""

from __future__ import annotations

import json

import typer

from dataipsum.api import RunResult


def _run_result_to_dict(result: RunResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "manifest_path": str(result.manifest_path),
        "tables": result.tables,
        "pending_chunks": result.pending_chunks,
    }


def echo_run_result(result: RunResult, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(_run_result_to_dict(result), ensure_ascii=False))
        return
    typer.echo(
        f"execução {result.status}: run_id={result.run_id} manifesto={result.manifest_path}",
        err=True,
    )


def echo_progress(message: str, *, quiet: bool) -> None:
    if not quiet:
        typer.echo(message, err=True)
