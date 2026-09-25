"""Varredura de segredos em `examples/` (DD-02 H.4, guardrail 4).

Procura padrões de chave (`sk-`, `AKIA`, `password:` literal) em todo texto
sob `examples/`. Chaves `*_env` são a exceção esperada pelo sanitizador do
DD-00 (§6.5): elas guardam só o NOME de uma variável de ambiente, nunca um
segredo, então `algo_env: "NOME_DA_VAR"` nunca dispara este teste — só um
valor que pareça um segredo de verdade (ex.: `sk-...`, `AKIA...`) dispararia,
mesmo dentro de uma chave `_env` mal usada.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "examples"

_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
_LITERAL_PASSWORD_FIELD = re.compile(r"(?im)^\s*password\s*:\s*\S")

_TEXT_SUFFIXES = {".yaml", ".yml", ".json", ".md", ".sh"}


def _example_text_files() -> list[Path]:
    return sorted(
        path for path in EXAMPLES_DIR.rglob("*") if path.is_file() and path.suffix in _TEXT_SUFFIXES
    )


@pytest.mark.parametrize("path", _example_text_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_arquivo_de_exemplo_nao_contem_padroes_de_segredo(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for pattern in _SECRET_VALUE_PATTERNS:
        assert not pattern.search(text), f"{path}: padrão de segredo encontrado ({pattern.pattern})"
    assert not _LITERAL_PASSWORD_FIELD.search(text), (
        f"{path}: campo 'password:' literal encontrado; use '*_env' (DD-00 §6.5)"
    )


def test_pelo_menos_um_arquivo_foi_verificado() -> None:
    assert _example_text_files(), "nenhum arquivo em 'examples/' foi encontrado para varrer"
