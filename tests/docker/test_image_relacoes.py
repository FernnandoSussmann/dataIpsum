"""Smoke test da imagem Docker para a trilha B (DD-01 §B.10, DD-00 §3.12).

Marcado `docker`: constrói a imagem de verdade e não roda no job de testes
rápidos (mesmo padrão de `tests/docker/test_image_base.py`).

A trilha B não tem fragmento próprio (§B.10: "Fragmento: nenhum") e a CLI
completa (`dataipsum generate ...`) é de outra trilha (G, DD-02) — ainda não
existe no runtime desta imagem. Por isso o smoke test aqui roda a
biblioteca diretamente dentro do container (`python -c ...`), com
`examples/relacoes/um-para-muitos.yaml` montado em `/schemas` (somente
leitura) e `--network none`: monta o plano e confere a integridade
referencial (toda FK de "pedidos_faixa"/"pedidos_zipf" existe no intervalo
de PKs de "usuarios"), sem gerar dados de outra tabela nem tocar a rede.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples" / "relacoes"
VERSION = "0.1.0"

_CHECK_SCRIPT = """
import numpy as np
from dataipsum.schema.loader import load_schema
from dataipsum.relations import RelationsPlanner

schema = load_schema("/schemas/um-para-muitos.yaml")
planner = RelationsPlanner()
plan = planner.plan(schema, seed=schema.seed, chunk_size=schema.chunk_size)

usuario_pks = set(planner.pk_at("usuarios", np.arange(plan.tables["usuarios"].rows)).to_pylist())
for tabela in ("pedidos_faixa", "pedidos_zipf"):
    n = plan.tables[tabela].rows
    fks = planner.row_at(tabela, np.arange(n), ["usuario_id"])["usuario_id"].to_pylist()
    assert set(fks) <= usuario_pks, f"FK fora do intervalo de PKs em {tabela}"
    assert n > 0, f"{tabela} sem linhas"

print("OK", plan.tables["pedidos_faixa"].rows, plan.tables["pedidos_zipf"].rows)
"""


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
    tag = "dataipsum:test-relacoes"
    _docker_build(tag)
    yield tag
    _docker_rm(tag)


def test_integridade_referencial_um_para_muitos(image: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{EXAMPLES_DIR}:/schemas:ro",
            "--entrypoint",
            "python",
            image,
            "-c",
            _CHECK_SCRIPT,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(result.stdout, file=sys.stderr)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("OK")
