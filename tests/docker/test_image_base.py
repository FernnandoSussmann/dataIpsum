"""Smoke tests da imagem Docker base (DD-00 §3.12.1, §3.12.3, §7.1).

Marcados `docker`: constroem a imagem de verdade (rede + `docker build`), por isso não rodam
no job de testes rápidos (`-m "not integration and not slow and not ray and not docker"`).

Construímos duas variantes:
  - `EXTRAS=""` (padrão): só as dependências obrigatórias.
  - um SUBCONJUNTO de `all` (`anthropic,postgres,mysql,kafka`), não `all` inteiro: `all` inclui
    `ray` e `toxicity` (que traz `torch`), pesados o bastante (centenas de MB a alguns GB de
    download) para tornar o teste impraticável neste ambiente. O subconjunto escolhido cobre
    extras que instalam via wheel puro-Python ou wheel binário sem compilador
    (`anthropic`, `PyMySQL`, `psycopg[binary]`, `confluent-kafka`), validando o mecanismo de
    `ARG EXTRAS` sem pagar o custo de `ray`/`torch`. Quando a trilha D (Ray) ou C (toxicidade)
    entrar, os testes de área delas (`test_image_execucao.py`, `test_image_llm.py`) cobrem
    especificamente esses extras mais pesados.
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
COMPILER_BINARIES = ("gcc", "cc", "make")


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


def _run(tag: str, *args: str, entrypoint: str | None = None) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "run", "--rm"]
    if entrypoint is not None:
        cmd += ["--entrypoint", entrypoint]
    cmd.append(tag)
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def _image_size_mb(tag: str) -> float:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Size}}", tag],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout.strip()) / (1024 * 1024)


@pytest.fixture(scope="module")
def image_default() -> Iterator[str]:
    tag = "dataipsum:test-s5-default"
    _docker_build(tag, extras="")
    size_mb = _image_size_mb(tag)
    print(f"\n[test_image_base] tamanho da imagem (EXTRAS=''): {size_mb:.1f} MiB", file=sys.stderr)
    yield tag
    _docker_rm(tag)


@pytest.fixture(scope="module")
def image_extras() -> Iterator[str]:
    tag = "dataipsum:test-s5-extras"
    extras = "anthropic,postgres,mysql,kafka"
    _docker_build(tag, extras=extras)
    size_mb = _image_size_mb(tag)
    print(
        f"\n[test_image_base] tamanho da imagem (EXTRAS={extras}): {size_mb:.1f} MiB",
        file=sys.stderr,
    )
    yield tag
    _docker_rm(tag)


def test_version(image_default: str) -> None:
    result = _run(image_default, "--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VERSION


def test_uid_e_nao_root(image_default: str) -> None:
    result = _run(image_default, "-u", entrypoint="id")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "10001"


def test_help(image_default: str) -> None:
    result = _run(image_default, "--help")
    assert result.returncode == 0, result.stderr
    assert "dataipsum" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_cmd_padrao_e_help(image_default: str) -> None:
    # `CMD ["--help"]`: sem argumentos, o container roda `dataipsum --help`.
    result = subprocess.run(
        ["docker", "run", "--rm", image_default], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr


def test_sem_compilador(image_default: str) -> None:
    which_cmd = f"which {' '.join(COMPILER_BINARIES)}"
    result = _run(image_default, "-c", which_cmd, entrypoint="sh")
    assert result.returncode != 0, (
        f"compilador encontrado na imagem final: stdout={result.stdout!r}"
    )
    assert result.stdout.strip() == ""


def test_label_versao_presente(image_default: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            '{{index .Config.Labels "org.opencontainers.image.version"}}',
            image_default,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == VERSION


def test_extras_version_e_help(image_extras: str) -> None:
    version_result = _run(image_extras, "--version")
    assert version_result.returncode == 0, version_result.stderr
    assert version_result.stdout.strip() == VERSION

    help_result = _run(image_extras, "--help")
    assert help_result.returncode == 0, help_result.stderr


def test_extras_sem_compilador(image_extras: str) -> None:
    which_cmd = f"which {' '.join(COMPILER_BINARIES)}"
    result = _run(image_extras, "-c", which_cmd, entrypoint="sh")
    assert result.returncode != 0, (
        f"compilador encontrado na imagem com extras: stdout={result.stdout!r}"
    )
    assert result.stdout.strip() == ""


def test_extras_uid_e_nao_root(image_extras: str) -> None:
    result = _run(image_extras, "-u", entrypoint="id")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "10001"
