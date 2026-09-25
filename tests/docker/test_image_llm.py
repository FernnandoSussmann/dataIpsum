"""Smoke tests da evolução da imagem pela trilha C (DD-01 §C.10, critério C-17).

Marcados `docker`: constroem a imagem de verdade (rede + `docker build`), por isso não rodam
no job de testes rápidos (`-m "not integration and not slow and not ray and not docker"`).
`EXTRAS=toxicity` com `PRELOAD_TOXICITY=1` baixa os pesos do Detoxify multilingual durante o
build (rede), então este arquivo é mais pesado que `tests/docker/test_image_base.py` e roda só
no job dedicado (ver a nota de `test_image_base.py` sobre extras pesados por área).
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
MODEL_CACHE_DIR = "/var/cache/dataipsum/models"
FAKE_API_KEY = "SEGREDO123-nunca-deveria-aparecer"


def _docker_build(tag: str, *, extras: str, preload_toxicity: bool = False) -> None:
    args = [
        "docker",
        "build",
        "--build-arg",
        f"VERSION={VERSION}",
        "--build-arg",
        f"EXTRAS={extras}",
    ]
    if preload_toxicity:
        args += ["--build-arg", "PRELOAD_TOXICITY=1"]
    args += ["-t", tag, str(REPO_ROOT)]
    subprocess.run(args, cwd=REPO_ROOT, check=True, timeout=3600)


def _docker_rm(tag: str) -> None:
    subprocess.run(["docker", "image", "rm", "-f", tag], check=False, capture_output=True)


def _run(
    tag: str, *args: str, extra_docker_args: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "run", "--rm", *(extra_docker_args or []), "--entrypoint", "sh", tag, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


@pytest.fixture(scope="module")
def image_sem_extras() -> Iterator[str]:
    tag = "dataipsum:test-llm-sem-extras"
    _docker_build(tag, extras="")
    yield tag
    _docker_rm(tag)


@pytest.fixture(scope="module")
def image_toxicity() -> Iterator[str]:
    tag = "dataipsum:test-llm-toxicity"
    _docker_build(tag, extras="toxicity", preload_toxicity=True)
    size_mb = int(
        subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Size}}", tag],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    ) / (1024 * 1024)
    print(
        f"\n[test_image_llm] tamanho da imagem (EXTRAS=toxicity): {size_mb:.1f} MiB",
        file=sys.stderr,
    )
    yield tag
    _docker_rm(tag)


def test_c17_variaveis_de_cache_apontam_para_diretorio_do_usuario_10001(
    image_sem_extras: str,
) -> None:
    result = _run(image_sem_extras, "-c", "echo $DATAIPSUM_MODEL_CACHE $TORCH_HOME $HF_HOME")
    assert result.returncode == 0, result.stderr
    values = result.stdout.split()
    assert values == [MODEL_CACHE_DIR, MODEL_CACHE_DIR, MODEL_CACHE_DIR]

    owner_result = _run(image_sem_extras, "-c", f"stat -c '%u:%g' {MODEL_CACHE_DIR}")
    assert owner_result.returncode == 0, owner_result.stderr
    assert owner_result.stdout.strip() == "10001:10001"


def test_c17_extras_vazio_continua_sem_torch(image_sem_extras: str) -> None:
    result = _run(image_sem_extras, "-c", "python -c 'import torch' 2>&1; echo EXIT:$?")
    assert "EXIT:0" not in result.stdout


def test_c17_classifica_offline_com_rootfs_read_only(image_toxicity: str) -> None:
    script = (
        'python -c "'
        "from dataipsum.llm.toxicity.detoxify_classifier import DetoxifyClassifier;"
        "c = DetoxifyClassifier();"
        "print(c.available());"
        "print(c.score(['texto de teste']))"
        '"'
    )
    result = _run(
        image_toxicity,
        "-c",
        script,
        extra_docker_args=["--network", "none", "--read-only"],
    )
    assert result.returncode == 0, result.stderr
    assert "True" in result.stdout


def test_c17_sem_pesos_e_sem_volume_gravavel_cai_para_wordlist_com_aviso(
    image_sem_extras: str,
) -> None:
    script = (
        'python -c "'
        "import logging; logging.basicConfig(level=logging.WARNING);"
        "from dataipsum.llm.toxicity import resolve_classifier;"
        "c = resolve_classifier('auto');"
        "print(type(c).__name__)"
        '"'
    )
    result = _run(
        image_sem_extras,
        "-c",
        script,
        extra_docker_args=["--network", "none", "--read-only"],
    )
    assert result.returncode == 0, result.stderr
    assert "WordlistClassifier" in result.stdout


def test_c17_history_e_inspect_nao_contem_chave_de_api(image_toxicity: str) -> None:
    history = subprocess.run(
        ["docker", "history", "--no-trunc", image_toxicity],
        capture_output=True,
        text=True,
        check=True,
    )
    assert FAKE_API_KEY not in history.stdout

    inspect = subprocess.run(
        ["docker", "image", "inspect", image_toxicity], capture_output=True, text=True, check=True
    )
    assert FAKE_API_KEY not in inspect.stdout
