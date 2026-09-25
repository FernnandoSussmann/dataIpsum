"""`dataipsum resume`: retoma uma execução pelo manifesto embutido em OUT
(DD-02 §G.3.1). Só faz parsing, chama `dataipsum.api`/`dataipsum.config` e
formata a saída.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dataipsum import api
from dataipsum.cli._errors import fail, translate_errors
from dataipsum.cli._output import echo_progress, echo_run_result
from dataipsum.cli._run_options import build_run_options, run_with_interrupt_drain
from dataipsum.config import SinkConfig
from dataipsum.manifest import read_manifest
from dataipsum.schema.models import Schema


def resume(
    out: Annotated[Path, typer.Argument(help="Diretório de saída de uma execução anterior.")],
    llm_only: Annotated[
        bool,
        typer.Option(
            "--llm-only",
            help=(
                "Retoma só os chunks pendentes de LLM. Aceita a flag, mas ela ainda não é "
                "repassada à façade: `RunOptions` (DD-00 §3.8) não tem esse campo até a "
                "trilha D existir."
            ),
        ),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Resumo final em JSON no stdout.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Mostra stack trace em erros.")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("-q", "--quiet", help="Silencia o progresso no stderr.")
    ] = False,
) -> None:
    """Retoma uma execução a partir do manifesto gravado em `<out>/_manifest.json`."""
    del llm_only  # ver docstring da opção: inerte até a trilha D existir
    with translate_errors(verbose=verbose, as_json=json_output, out_dir=out):
        manifest = read_manifest(out)
        schema = Schema.model_validate(manifest.schema)
        sink_dict = manifest.sink
        sink_options = sink_dict.get("options", {})
        sink = SinkConfig(
            kind=str(sink_dict.get("kind", "")),
            options=dict(sink_options) if isinstance(sink_options, dict) else {},
        )
        options = build_run_options(out_dir=out, sink=sink, schema=schema, cli_overrides={})

        echo_progress(f"retomando execução em '{out}'...", quiet=quiet)
        result = run_with_interrupt_drain(
            lambda: api.resume(out, options), out_dir=out, schema=schema, options=options
        )
        echo_run_result(result, as_json=json_output)
        if result.status != "completed":
            raise fail(
                f"execução '{result.status}' com {result.pending_chunks} chunk(s) pendente(s). "
                f"Rode 'dataipsum resume {out}' de novo para retomar.",
                as_json=json_output,
            )
