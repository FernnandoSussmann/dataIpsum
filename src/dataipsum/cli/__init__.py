"""Esqueleto de CLI do S1 (DD-00 §3.12.4). Substituído pela CLI completa da trilha G (DD-02)."""

from __future__ import annotations

import importlib.metadata

import typer

from dataipsum.registry import Registry

app = typer.Typer(
    add_completion=False, help="dataIpsum: gerador de dados sintéticos determinístico."
)


def _echo_version(show: bool) -> None:
    if show:
        typer.echo(importlib.metadata.version("dataipsum"))
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_echo_version, is_eager=True, help="Mostra a versão e sai."
    ),
) -> None:
    return None


@app.command()
def gen() -> None:
    """Gera dados a partir de um schema. Implementado pela trilha G (DD-02)."""
    raise NotImplementedError("trilha G (DD-02)")


def register(registry: Registry) -> None:
    """Vazio: a trilha G não registra geradores/sinks."""
