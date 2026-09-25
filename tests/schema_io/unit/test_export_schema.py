"""Testes de `export_schema` (DD-02 §F.3.3, §F.6): escrita atômica e confinada."""

from __future__ import annotations

import json
from pathlib import Path

import fastavro
import pytest
import sqlglot

from conftest import build_schema
from dataipsum.errors import OutputDirError, SchemaError
from dataipsum.schema.models import Schema
from dataipsum.schema_io import export_schema


def test_export_ddl_grava_dialect_sql(loja_schema: Schema, tmp_path: Path) -> None:
    paths = export_schema(loja_schema, "ddl", "postgres", out_dir=tmp_path)
    assert paths == [tmp_path / "postgres.sql"]
    content = paths[0].read_text(encoding="utf-8")
    assert "CREATE TABLE" in content
    sqlglot.parse(content, read="postgres")


def test_export_ddl_sem_dialect_e_erro(loja_schema: Schema, tmp_path: Path) -> None:
    with pytest.raises(SchemaError):
        export_schema(loja_schema, "ddl", out_dir=tmp_path)


def test_export_avro_grava_um_arquivo_por_tabela(loja_schema: Schema, tmp_path: Path) -> None:
    paths = export_schema(loja_schema, "avro", out_dir=tmp_path)
    assert {p.name for p in paths} == {"usuarios.avsc", "produtos.avsc", "pedidos.avsc"}
    for path in paths:
        fastavro.parse_schema(json.loads(path.read_text(encoding="utf-8")))


def test_export_cria_diretorio_de_saida(loja_schema: Schema, tmp_path: Path) -> None:
    out_dir = tmp_path / "aninhado" / "_schema" / "ddl"
    export_schema(loja_schema, "ddl", "postgres", out_dir=out_dir)
    assert (out_dir / "postgres.sql").exists()


def test_export_nao_deixa_arquivo_temporario(loja_schema: Schema, tmp_path: Path) -> None:
    export_schema(loja_schema, "avro", out_dir=tmp_path)
    leftover_tmp_files = [
        p for p in tmp_path.iterdir() if p.name.startswith(".") and "tmp-" in p.name
    ]
    assert leftover_tmp_files == []


def test_export_formato_desconhecido_e_erro(loja_schema: Schema, tmp_path: Path) -> None:
    with pytest.raises(SchemaError):
        export_schema(loja_schema, "csv", out_dir=tmp_path)  # type: ignore[arg-type]


def test_export_recusa_symlink_no_caminho_final(loja_schema: Schema, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    outside_target = tmp_path / "fora.sql"
    outside_target.write_text("conteúdo antigo", encoding="utf-8")
    (out_dir / "postgres.sql").symlink_to(outside_target)
    with pytest.raises(OutputDirError):
        export_schema(loja_schema, "ddl", "postgres", out_dir=out_dir)


def test_export_reexecucao_sobrescreve_atomically(loja_schema: Schema, tmp_path: Path) -> None:
    export_schema(loja_schema, "ddl", "postgres", out_dir=tmp_path)
    first_content = (tmp_path / "postgres.sql").read_text(encoding="utf-8")
    paths = export_schema(loja_schema, "ddl", "postgres", out_dir=tmp_path)
    second_content = paths[0].read_text(encoding="utf-8")
    assert first_content == second_content


def test_export_avro_usa_schema_sem_tabelas_extra(tmp_path: Path) -> None:
    schema = build_schema(
        {
            "version": 1,
            "tables": [
                {
                    "name": "t",
                    "rows": 1,
                    "primary_key": {"columns": ["id"], "strategy": "sequence"},
                    "columns": [{"name": "id", "type": "int"}],
                }
            ],
        }
    )
    paths = export_schema(schema, "avro", out_dir=tmp_path)
    assert len(paths) == 1
