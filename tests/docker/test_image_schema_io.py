"""Smoke tests da evolução da imagem Docker pela trilha F (DD-02 §F.10).

Marcados `docker`: constroem a imagem de verdade e não rodam no job de testes rápidos.

A trilha F não adiciona pacote de SO nem extra (`sqlglot` já está na base, DD-00 S1), então
usamos a imagem padrão (`EXTRAS=""`) da mesma forma que `test_image_base.py`. Os comandos
`schema export`/`schema import` são da CLI (trilha G, DD-02); estes testes validam o
comportamento **dentro do container** depois que a CLI expuser esses comandos (F.3.3/F.3.4)
sobre `dataipsum.schema_io` — se a CLI ainda não os expuser quando este teste rodar, ele falha
de forma explícita e localizável (mensagem do Typer), em vez de silenciosamente não cobrir a
área da trilha F na imagem.
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
LOJA_SCHEMA_YAML = """\
version: 1
name: loja
tables:
  - name: usuarios
    rows: 10
    primary_key: {columns: [id], strategy: sequence, start: 1}
    columns:
      - {name: id, type: int}
      - {name: nome, type: nome_proprio, max_length: 120}
"""
LOJA_DDL_SQL = "CREATE TABLE clientes (id SERIAL PRIMARY KEY, cpf CHAR(11) NOT NULL);\n"


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
    tag = "dataipsum:test-schema-io"
    _docker_build(tag)
    yield tag
    _docker_rm(tag)


def test_schema_export_ddl_grava_em_out_sem_rede(image: str, tmp_path: Path) -> None:
    schema_path = tmp_path / "loja.yaml"
    schema_path.write_text(LOJA_SCHEMA_YAML, encoding="utf-8")
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
            f"{schema_path}:/schemas/loja.yaml:ro",
            "-v",
            f"{out_dir}:/out",
            image,
            "schema",
            "export",
            "/schemas/loja.yaml",
            "--format",
            "ddl",
            "--dialect",
            "postgres",
            "-o",
            "/out",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    ddl_path = out_dir / "postgres.sql"
    assert ddl_path.exists()
    assert "CREATE TABLE" in ddl_path.read_text(encoding="utf-8")


def test_schema_export_avro_grava_um_avsc_por_tabela(image: str, tmp_path: Path) -> None:
    schema_path = tmp_path / "loja.yaml"
    schema_path.write_text(LOJA_SCHEMA_YAML, encoding="utf-8")
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
            f"{schema_path}:/schemas/loja.yaml:ro",
            "-v",
            f"{out_dir}:/out",
            image,
            "schema",
            "export",
            "/schemas/loja.yaml",
            "--format",
            "avro",
            "-o",
            "/out",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert (out_dir / "usuarios.avsc").exists()


def test_schema_import_de_ddl_montado_gera_yaml_valido(image: str, tmp_path: Path) -> None:
    ddl_path = tmp_path / "clientes.sql"
    ddl_path.write_text(LOJA_DDL_SQL, encoding="utf-8")
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
            f"{ddl_path}:/schemas/clientes.sql:ro",
            "-v",
            f"{out_dir}:/out",
            image,
            "schema",
            "import",
            "/schemas/clientes.sql",
            "--dialect",
            "postgres",
            "-o",
            "/out/clientes.yaml",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    generated_yaml = out_dir / "clientes.yaml"
    assert generated_yaml.exists()
    assert "cpf" in generated_yaml.read_text(encoding="utf-8")


def test_import_nunca_abre_conexao_de_rede(image: str, tmp_path: Path) -> None:
    """F.9: `schema import` funciona com `--network none` (nenhuma conexão é aberta)."""
    ddl_path = tmp_path / "clientes.sql"
    ddl_path.write_text(LOJA_DDL_SQL, encoding="utf-8")
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
            f"{ddl_path}:/schemas/clientes.sql:ro",
            "-v",
            f"{out_dir}:/out",
            image,
            "schema",
            "import",
            "/schemas/clientes.sql",
            "--dialect",
            "postgres",
            "-o",
            "/out/clientes.yaml",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(f"\n[test_image_schema_io] saída: {result.stdout}", file=sys.stderr)
    assert result.returncode == 0, result.stderr
