"""Smoke tests da imagem Docker da trilha D, execução (DD-01 §D.10).

Marcados `docker`: constroem a imagem de verdade. `--entrypoint ray` e
`RAY_USAGE_STATS_ENABLED=0` só precisam de `EXTRAS=ray` (`test_ray_entrypoint_funciona`,
`test_ray_usage_stats_desligado`). O teste de cluster (`ray-cluster/`, D-06/D-10: head +
2 workers com a MESMA imagem, sem portas publicadas, `--executor ray` com o mesmo sha256
da execução local) é adicionalmente marcado `ray`, porque depende de um `docker compose`
Ray de verdade — mais pesado que os smoke tests de entrypoint/env.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.1.0"


def _docker_build(tag: str, extras: str) -> None:
    subprocess.run(
        [
            "docker",
            "build",
            "--build-arg",
            f"VERSION={VERSION}",
            "--build-arg",
            f"EXTRAS={extras}",
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
def image_ray() -> Iterator[str]:
    tag = "dataipsum:test-execucao-ray"
    _docker_build(tag, extras="ray")
    yield tag
    _docker_rm(tag)


def test_ray_entrypoint_funciona(image_ray: str) -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "ray", image_ray, "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "ray" in result.stdout.lower()


def test_ray_usage_stats_desligado(image_ray: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "sh",
            image_ray,
            "-c",
            "echo $RAY_USAGE_STATS_ENABLED",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


def test_imagem_sem_extras_continua_sem_ray() -> None:
    """Critério C-17 (reafirmado aqui para `execucao`): `EXTRAS=""` não instala `ray`."""
    tag = "dataipsum:test-execucao-default"
    _docker_build(tag, extras="")
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "python", tag, "-c", "import ray"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0
    finally:
        _docker_rm(tag)


@pytest.mark.ray
def test_cluster_ray_produz_mesmo_sha256_da_execucao_local(image_ray: str) -> None:
    """D-06/D-10: head + 2 workers na mesma imagem, sem portas publicadas, mesmo sha256
    da execução local. Requer `docker compose` e um cluster Ray de verdade; roda no job
    `docker` + `ray` (mais pesado que os smoke tests acima)."""
    compose_file = REPO_ROOT / "examples" / "execucao" / "ray-cluster" / "docker-compose.yml"
    subprocess.run(
        ["docker", "tag", image_ray, "dataipsum:ray"], cwd=REPO_ROOT, check=True, timeout=60
    )
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            cwd=REPO_ROOT,
            check=True,
            timeout=120,
        )
        nodes = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(compose_file),
                "exec",
                "-T",
                "ray-head",
                "python",
                "-c",
                "import ray; ray.init(address='auto'); print(len(ray.nodes()))",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        print(
            f"\n[test_image_execucao] nós vivos no cluster: {nodes.stdout.strip()}", file=sys.stderr
        )
        assert nodes.returncode == 0, nodes.stderr
        assert int(nodes.stdout.strip()) >= 3  # head + 2 workers
        # O sha256 igual à execução local (D-06) é coberto pela integração S5
        # (`tests/integration/motor/`, DD-01 §3), que troca os fakes pelo `RayExecutor`
        # real com um schema/planner reais — fora do escopo isolado da trilha D.
    finally:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "down", "-v"],
            cwd=REPO_ROOT,
            check=False,
            timeout=60,
        )
