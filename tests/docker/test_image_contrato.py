"""Smoke test da imagem Docker para a trilha H (DD-02 H.10).

Marcado `docker`: constrói a imagem de verdade, por isso não roda no job de
testes rápidos (`-m "not integration and not slow and not ray and not docker"`).

A trilha H não muda nenhum fragmento (nenhum passo novo de imagem, H.10): o
JSON Schema é gerado pelo código, e `schemas/`, `examples/` e `docs/` ficam
fora da imagem via `.dockerignore`. O único smoke test da área roda
`dataipsum schema jsonschema` dentro do container e compara a saída, byte a
byte, com o arquivo versionado `schemas/dataipsum-schema.v1.json`.

Esse comando é implementado pela trilha G (CLI, DD-02 G.3.1: `dataipsum
schema jsonschema [-o FILE]`), que roda em paralelo com esta trilha neste
marco: até o merge de G, este teste falha com "no such command", o que é
esperado num worktree isolado de H (DD-02 §0) e se resolve na integração do
S5.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.1.0"
VERSIONED_SCHEMA_PATH = REPO_ROOT / "schemas" / "dataipsum-schema.v1.json"


def _docker_build(tag: str) -> None:
    subprocess.run(
        ["docker", "build", "--build-arg", f"VERSION={VERSION}", "-t", tag, str(REPO_ROOT)],
        cwd=REPO_ROOT,
        check=True,
        timeout=1800,
    )


def _docker_rm(tag: str) -> None:
    subprocess.run(["docker", "image", "rm", "-f", tag], check=False, capture_output=True)


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    tag = "dataipsum:test-contrato"
    _docker_build(tag)
    yield tag
    _docker_rm(tag)


def test_schema_jsonschema_saida_identica_ao_arquivo_versionado(image: str) -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "none", image, "schema", "jsonschema"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    produced = json.loads(result.stdout)
    expected = json.loads(VERSIONED_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert produced == expected
