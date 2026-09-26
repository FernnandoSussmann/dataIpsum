"""Smoke test da imagem Docker para a trilha A (DD-01 A.10).

Marcado `docker`: constrói a imagem de verdade, por isso não roda no job de
testes rápidos (mesmo filtro de `tests/docker/test_image_base.py`).

`docker/fragments/tipos.*` continuam vazios (A.10): a única mudança de
imagem desta trilha é os dados embarcados (`types/data/*.{yaml,json}`)
entrarem como *package data* no wheel copiado para a imagem — sem isso,
`dataipsum.types` não encontra `bins.yaml`/`names_pt_BR.json`/
`lorem_pt_BR.json` dentro do container.

Este smoke test depende do comando `dataipsum gen` (CLI, trilha G) e da
execução local (trilha D), que ainda não existem neste worktree isolado
(S1 roda em paralelo com S2/S3/S4, DD-01 §0). Ele fica escrito e marcado
`docker` desde já, como a trilha A pede, e passa a valer a partir do S5
(integração), quando `dataipsum gen` existir de verdade.
"""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from dataipsum.types import is_valid_cpf, is_valid_email, is_valid_rg_sp, luhn_is_valid

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.1.0"
ROWS = 100


def _docker_build(tag: str) -> None:
    subprocess.run(
        [
            "docker",
            "build",
            "--build-arg",
            f"VERSION={VERSION}",
            "--build-arg",
            "EXTRAS=",
            "-t",
            tag,
            str(REPO_ROOT),
        ],
        cwd=REPO_ROOT,
        check=True,
        timeout=1800,
    )


def _docker_rm(tag: str) -> None:
    subprocess.run(["docker", "image", "rm", "-f", tag], check=False, capture_output=True)


@pytest.fixture(scope="module")
def image_tipos() -> Iterator[str]:
    tag = "dataipsum:test-tipos"
    _docker_build(tag)
    print(f"\n[test_image_tipos] imagem construída: {tag}", file=sys.stderr)
    yield tag
    _docker_rm(tag)


def test_gen_sem_rede_produz_100_linhas_validas(image_tipos: str) -> None:
    with tempfile.TemporaryDirectory() as host_out_dir:
        container_out = "/out"
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "-v",
                f"{host_out_dir}:{container_out}",
                image_tipos,
                "gen",
                "--table",
                "t",
                "--rows",
                str(ROWS),
                "--col",
                "c:cpf",
                "--col",
                "r:rg",
                "--col",
                "k:cartao_credito",
                "--col",
                "e:email",
                "--col",
                "n:nome_proprio",
                "-o",
                container_out,
                "--format",
                "csv",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr

        csv_files = list(Path(host_out_dir).rglob("*.csv"))
        assert csv_files, f"nenhum CSV gerado em {host_out_dir}: {result.stdout}"

        rows = [row for path in csv_files for row in csv.DictReader(path.open(encoding="utf-8"))]
        assert len(rows) == ROWS
        assert all(is_valid_cpf(row["c"]) for row in rows)
        assert all(is_valid_rg_sp(row["r"]) for row in rows)
        assert all(luhn_is_valid(row["k"]) for row in rows)
        assert all(is_valid_email(row["e"]) for row in rows)
        assert all(row["n"] for row in rows)
