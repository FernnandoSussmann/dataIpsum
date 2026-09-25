"""CLI Typer do dataIpsum (DD-02, trilha G, §G.3.1).

A CLI só faz parsing, chama a façade (`dataipsum.api`/`dataipsum.config`) e
formata a saída — nenhuma regra de negócio mora aqui (§G.2, DD-00 §3.10). Um
teste de arquitetura (`tests/cli/unit/test_architecture.py`) garante que este
pacote não importa `types/`, `relations/`, `llm/`, `execution/`, `sinks/` nem
`schema_io/` diretamente.
"""

from __future__ import annotations

import importlib.metadata
import signal
from types import FrameType

import typer

from dataipsum.cli._errors import ErrorTranslatingGroup
from dataipsum.cli.gen import gen
from dataipsum.cli.resume import resume
from dataipsum.cli.schema import schema_app


def _raise_keyboard_interrupt(signum: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt()


app = typer.Typer(
    cls=ErrorTranslatingGroup,
    add_completion=False,
    help="dataIpsum: gerador de dados sintéticos determinístico.",
)


def _echo_version(show: bool) -> None:
    if show:
        typer.echo(importlib.metadata.version("dataipsum"))
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False, "--version", callback=_echo_version, is_eager=True, help="Mostra a versão e sai."
    ),
) -> None:
    # `docker stop` manda SIGTERM, não SIGINT: tratamos os dois como Ctrl+C
    # (§G.3.1) para que o driver drene os chunks em voo do mesmo jeito num
    # container quanto num terminal interativo.
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)


app.command(name="gen", help="Gera dados a partir de um SCHEMA (arquivo) ou de flags inline.")(gen)
app.command(name="resume", help="Retoma uma execução pelo manifesto de OUT.")(resume)
app.add_typer(schema_app, name="schema", help="Valida, exporta, importa e descreve o schema.")

__all__ = ["app"]
