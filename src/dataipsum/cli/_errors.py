"""Tradução de erros e do código de saída da CLI (DD-02, trilha G, §G.3.1, §G.5.6).

A CLI só conhece dois códigos de saída: `0` (sucesso) e `1` (qualquer erro,
incluindo uso incorreto do Click, `partial` e Ctrl+C). `ErrorTranslatingGroup`
força o `Typer`/`Click` subjacente a rodar em modo não standalone (§G.3.1) para
que o próprio código de saída 2 do Click vire 1, e `translate_errors` cobre os
erros levantados dentro do corpo de cada comando.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError as PydanticValidationError

from dataipsum.errors import DataIpsumError, SchemaError

_RESUME_SUGGESTION = "rode 'dataipsum resume {out_dir}' para retomar essa execução"


def echo_error(message: str, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps({"status": "error", "error": message}, ensure_ascii=False))
    else:
        typer.echo(message, err=True)


def fail(message: str, *, as_json: bool = False) -> typer.Exit:
    echo_error(message, as_json=as_json)
    return typer.Exit(code=1)


def _format_pydantic_error_detail(loc: tuple[object, ...], message: str) -> str:
    path = ".".join(str(part) for part in loc) or "$"
    return f"{path}: {message}"


def _format_pydantic_error(exc: PydanticValidationError) -> str:
    return "; ".join(
        _format_pydantic_error_detail(error["loc"], str(error["msg"])) for error in exc.errors()
    )


def _show_traceback_if_verbose(*, verbose: bool) -> None:
    if verbose:
        typer.echo(traceback.format_exc(), err=True)


@contextmanager
def translate_errors(
    *, verbose: bool = False, as_json: bool = False, out_dir: Path | None = None
) -> Iterator[None]:
    """Converte qualquer falha da façade (ou Ctrl+C) em `typer.Exit(1)` com mensagem em pt-BR.

    Nunca deixa uma exceção crua propagar até o runner do Click: sem isso, uma
    `NotImplementedError` de uma trilha ainda não implementada apareceria como
    traceback não tratado em vez do código de saída 1 previsto em §G.3.1.
    """
    try:
        yield
    except KeyboardInterrupt:
        _show_traceback_if_verbose(verbose=verbose)
        suggestion = f" {_RESUME_SUGGESTION.format(out_dir=out_dir)}." if out_dir else ""
        raise fail(f"execução interrompida (Ctrl+C).{suggestion}", as_json=as_json) from None
    except SchemaError as exc:
        _show_traceback_if_verbose(verbose=verbose)
        raise fail(str(exc), as_json=as_json) from None
    except PydanticValidationError as exc:
        _show_traceback_if_verbose(verbose=verbose)
        raise fail(_format_pydantic_error(exc), as_json=as_json) from None
    except NotImplementedError as exc:
        _show_traceback_if_verbose(verbose=verbose)
        raise fail(f"funcionalidade ainda não implementada: {exc}", as_json=as_json) from None
    except DataIpsumError as exc:
        _show_traceback_if_verbose(verbose=verbose)
        raise fail(str(exc), as_json=as_json) from None
    except OSError as exc:
        _show_traceback_if_verbose(verbose=verbose)
        raise fail(f"erro de E/S: {exc}", as_json=as_json) from None


def _exception_message(exc: BaseException) -> str:
    show = getattr(exc, "show", None)
    if callable(show):
        show()
        return ""
    return f"erro: {exc}"


class ErrorTranslatingGroup(typer.core.TyperGroup):
    """`TyperGroup` que roda em modo não standalone e converte o código 2 do
    Click (erro de uso) em 1 (§G.3.1)."""

    def main(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["standalone_mode"] = False
        try:
            result = super().main(*args, **kwargs)
        except (KeyboardInterrupt, typer.Abort):
            typer.echo("execução interrompida (Ctrl+C)", err=True)
            raise SystemExit(1) from None
        except Exception as exc:  # noqa: BLE001 -- qualquer falha de parsing vira código 1
            message = _exception_message(exc)
            if message:
                typer.echo(message, err=True)
            raise SystemExit(1) from None
        code = result if isinstance(result, int) else 0
        raise SystemExit(0 if code == 0 else 1)
