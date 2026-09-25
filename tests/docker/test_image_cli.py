"""Smoke tests da CLI completa dentro da imagem (DD-02, trilha G, §G.10).

Marcados `docker`: constroem a imagem de verdade e não rodam no job de testes
rápidos (`-m "not integration and not slow and not ray and not docker"`).

A CLI completa substitui o esqueleto do DD-00 S1 sem mudar o `ENTRYPOINT
["dataipsum"]`: nenhum fragmento de `docker/fragments/cli-docker.*` é
necessário (§G.10, "Fragmento: nenhum").
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[2]
TAG = "dataipsum:test-cli"

_HELP_TARGETS: tuple[tuple[str, ...], ...] = (
    (),
    ("gen",),
    ("resume",),
    ("schema",),
    ("schema", "validate"),
    ("schema", "export"),
    ("schema", "import"),
    ("schema", "jsonschema"),
)


def _docker_build() -> None:
    subprocess.run(
        ["docker", "build", "-t", TAG, str(REPO_ROOT)],
        cwd=REPO_ROOT,
        check=True,
        timeout=1800,
    )


def _run(*args: str, network_none: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "run", "--rm"]
    if network_none:
        cmd += ["--network", "none"]
    cmd.append(TAG)
    cmd.extend(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    _docker_build()
    yield TAG
    subprocess.run(["docker", "image", "rm", "-f", TAG], check=False, capture_output=True)


@pytest.mark.parametrize("target", _HELP_TARGETS, ids=lambda t: " ".join(t) or "root")
def test_help_de_cada_comando(image: str, target: tuple[str, ...]) -> None:
    result = _run(*target, "--help")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


def test_codigo_0_em_sucesso(image: str) -> None:
    result = _run("schema", "jsonschema")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["title"] == "Schema"


def test_codigo_1_em_erro_de_uso(image: str) -> None:
    result = _run(
        "gen",
        "--table",
        "usuarios",
        "--rows",
        "1",
        "--col",
        "id:int:pk",
        "-o",
        "/out",
        "--format",
        "xml",
    )
    assert result.returncode == 1


def _make_world_accessible(path: Path, *, writable: bool = False) -> None:
    # `tmp_path` do pytest nasce com `700`: o container roda como UID 10001
    # (não o dono do host), que precisa de `x` em cada diretório do caminho e
    # `r`/`rw` no próprio caminho para ler ou gravar no bind mount.
    mode = 0o777 if writable else (0o755 if path.is_dir() else 0o644)
    os.chmod(path, mode)
    for parent in path.parents:
        os.chmod(parent, 0o755)
        if parent.name.startswith("pytest-of-"):
            break


def test_codigo_1_em_schema_invalido(image: str, tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(
        "version: 1\ntables:\n- name: t\n  rows: 1\n"
        "  primary_key: {columns: [id], strategy: sequence}\n"
        "  columns:\n  - {name: id, type: int, invalid_ratio: 2}\n",
        encoding="utf-8",
    )
    _make_world_accessible(schema_path)
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{tmp_path}:/schemas:ro",
            TAG,
            "schema",
            "validate",
            "/schemas/schema.yaml",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1
    assert "invalid_ratio" in result.stderr


_SIGTERM_PROBE_SCRIPT = """
import signal
import time
from pathlib import Path

from dataipsum.cli import _raise_keyboard_interrupt
from dataipsum.cli._run_options import run_with_interrupt_drain
from dataipsum.config import RunOptions, SinkConfig
from dataipsum.schema.models import ColumnSpec, PrimaryKeySpec, Schema, TableSpec

signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)

schema = Schema(
    version=1,
    tables=[
        TableSpec(
            name="t",
            rows=1,
            primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
            columns=[ColumnSpec(name="id", type="int")],
        )
    ],
)
options = RunOptions(out_dir=Path("/out"), sink=SinkConfig(kind="csv"))
run_with_interrupt_drain(
    lambda: time.sleep(30), out_dir=Path("/out"), schema=schema, options=options
)
"""


def test_docker_stop_grava_manifesto_partial(image: str, tmp_path: Path) -> None:
    """`docker stop` manda SIGTERM: a CLI trata isso como Ctrl+C (§G.3.1),
    grava o manifesto `partial` (fallback, enquanto a trilha D não existe) e
    sai com código != 0.

    Como `api.generate` ainda é um stub que levanta `NotImplementedError` na
    hora (trilha D não existe), não há trabalho de verdade para interromper
    dentro de `gen`. Este teste chama `run_with_interrupt_drain` diretamente
    (via `--entrypoint python`, código real da imagem) com uma chamada que
    dorme por tempo suficiente para o `docker stop` alcançá-la de verdade.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    _make_world_accessible(out_dir, writable=True)
    container_name = "dataipsum-test-cli-sigterm"
    subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True)

    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-v",
            f"{out_dir}:/out",
            "--entrypoint",
            "python",
            TAG,
            "-c",
            _SIGTERM_PROBE_SCRIPT,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        time.sleep(1.0)
        subprocess.run(
            ["docker", "stop", "--timeout", "15", container_name], check=True, timeout=30
        )
        inspect = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.ExitCode}}", container_name],
            capture_output=True,
            text=True,
            check=True,
        )
        assert inspect.stdout.strip() != "0"
        manifest_path = out_dir / "_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "partial"
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True)
