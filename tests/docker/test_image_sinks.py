"""Smoke tests da imagem Docker para a trilha E (sinks, DD-02, E.10).

Marcados `docker`: constroem a imagem de verdade, não rodam no gate rápido.

A CLI completa (`dataipsum gen ...`) é entregue pela trilha G (DD-02) e ainda não
existe neste worktree; por isso os smoke tests funcionais abaixo exercitam os
sinks diretamente via `python -c` (importando `dataipsum.sinks`), em vez de por
`dataipsum gen --format parquet` como o enunciado de E.10 descreve literalmente.
Quando a trilha G entregar a CLI, o smoke test funcional pode trocar para
`docker run ... gen --format parquet ...` sem mudar o que é verificado (escrita
em `/out` como UID 10001, com `--network none`).
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION = "0.1.0"
COMPILER_BINARIES = ("gcc", "cc", "make")
SINKS_EXTRAS = "postgres,mysql,kafka"

_PARQUET_SMOKE_SCRIPT = """
import pyarrow as pa
from dataipsum.contracts.sink import RunContext
from dataipsum.schema.models import ColumnSpec, PrimaryKeySpec, TableSpec
from dataipsum.sinks.parquet_sink import ParquetSink

schema = pa.schema([("id", pa.int64())])
table = TableSpec(
    name="usuarios",
    rows=1,
    primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence", start=1),
    columns=[ColumnSpec(name="id", type="int64")],
)
sink = ParquetSink()
sink.open(RunContext(run_id="smoke", out_dir="/out", seed=1), table, schema)
sink.write_chunk(1, pa.record_batch([pa.array([1])], schema=schema))
print("ok")
"""


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
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


@pytest.fixture(scope="module")
def image_sinks() -> Iterator[str]:
    tag = "dataipsum:test-sinks"
    _docker_build(tag, extras=SINKS_EXTRAS)
    yield tag
    _docker_rm(tag)


def test_builds_with_db_and_kafka_extras_without_compiler(image_sinks: str) -> None:
    which_cmd = f"which {' '.join(COMPILER_BINARIES)}"
    result = _run(image_sinks, "-c", which_cmd, entrypoint="sh")
    assert result.returncode != 0
    assert result.stdout.strip() == ""


def test_optional_drivers_import_inside_container(image_sinks: str) -> None:
    result = _run(
        image_sinks,
        "-c",
        "import psycopg, pymysql, confluent_kafka; print('ok')",
        entrypoint="python",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_parquet_sink_writes_to_out_as_uid_10001_with_no_network(
    image_sinks: str, tmp_path: Path
) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{out_dir}:/out",
            "--entrypoint",
            "python",
            image_sinks,
            "-c",
            _PARQUET_SMOKE_SCRIPT,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
    written_file = out_dir / "usuarios" / "part-00001.parquet"
    assert written_file.exists()
    file_stat = written_file.stat()
    assert file_stat.st_uid == 10001
