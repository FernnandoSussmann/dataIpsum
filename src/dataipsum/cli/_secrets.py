"""Parsing e guardrail de segredos de `--sink-opt` (DD-02 §G.5.1, DD-00 §6.5).

A CLI nunca aceita `--password`/`--api-key` como flags de primeira classe, e
`--sink-opt` com uma chave que pareça um segredo só é aceita quando termina em
`_env` (ela carrega o *nome* de uma variável de ambiente, nunca o valor).
"""

from __future__ import annotations

import re

import typer

_SECRET_KEY_PATTERN = re.compile(r"(?i)pass|secret|token|key")
_ENV_SUFFIX = "_env"


def _split_key_value(raw: str) -> tuple[str, str]:
    key, separator, value = raw.partition("=")
    if not separator or not key:
        raise typer.BadParameter(f"'--sink-opt {raw}' inválido: use o formato 'chave=valor'")
    return key, value


def _reject_if_secret_like(key: str) -> None:
    if key.lower().endswith(_ENV_SUFFIX):
        return
    if _SECRET_KEY_PATTERN.search(key):
        raise typer.BadParameter(
            f"'--sink-opt {key}=...' recusado: a chave '{key}' parece um segredo. "
            f"Use '{key}_env' com o NOME de uma variável de ambiente, nunca o valor."
        )


def parse_sink_options(raw_options: list[str]) -> dict[str, object]:
    """Converte `--sink-opt chave=valor` (repetível) num `dict`, recusando segredos.

    Os valores nunca entram na mensagem de erro (§6.5): só o nome da chave é citado.
    """
    pairs = [_split_key_value(raw) for raw in raw_options]
    for key, _value in pairs:
        _reject_if_secret_like(key)
    return dict(pairs)
