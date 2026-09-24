"""Testes do loader de schema (DD-00 §7.1: schema/loader.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import FULL_EXAMPLE
from dataipsum.errors import SchemaError
from dataipsum.schema.loader import (
    MAX_COLUMNS_PER_TABLE,
    MAX_DEPTH,
    MAX_FILE_SIZE_BYTES,
    MAX_PARAMS_BYTES,
    MAX_TABLES,
    load_schema,
    validate,
)
from dataipsum.schema.models import Schema, ValidationContext

MINIMAL_YAML = """
version: 1
tables:
  - name: usuarios
    rows: 10
    primary_key: {columns: [id], strategy: sequence}
    columns:
      - {name: id, type: int}
"""


def _minimal_table(index: int = 0) -> dict[str, object]:
    return {
        "name": f"t{index}",
        "rows": 10,
        "primary_key": {"columns": ["id"], "strategy": "sequence"},
        "columns": [{"name": "id", "type": "int"}],
    }


def _minimal_doc(**overrides: object) -> dict[str, object]:
    doc: dict[str, object] = {"version": 1, "tables": [_minimal_table()]}
    doc.update(overrides)
    return doc


# --- carregamento válido -----------------------------------------------------


def test_carrega_yaml_minimo() -> None:
    schema = load_schema(MINIMAL_YAML)
    assert schema.tables[0].name == "usuarios"


def test_carrega_yaml_completo_do_exemplo_3_3() -> None:
    text = yaml.safe_dump(FULL_EXAMPLE, sort_keys=False)
    schema = load_schema(text)
    assert [t.name for t in schema.tables] == ["usuarios", "produtos", "pedidos"]
    assert schema.locale == "pt_BR"


def test_carrega_a_partir_de_um_dict_ja_parseado() -> None:
    schema = load_schema(_minimal_doc())
    assert isinstance(schema, Schema)


def test_carrega_a_partir_de_um_path(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.yaml"
    schema_path.write_text(MINIMAL_YAML, encoding="utf-8")
    schema = load_schema(schema_path)
    assert schema.tables[0].name == "usuarios"


def test_padroes_aplicados_locale_chunk_size_null_ratio() -> None:
    schema = load_schema(_minimal_doc())
    assert schema.locale == "pt_BR"
    assert schema.chunk_size == 10_000
    assert schema.tables[0].columns[0].null_ratio == 0.0


# --- YAML seguro: âncoras, aliases, tags customizadas -----------------------


def test_rejeita_alias_e_ancora() -> None:
    text = """
version: 1
tables:
  - &base
    name: t
    rows: 10
    primary_key: {columns: [id], strategy: sequence}
    columns:
      - {name: id, type: int}
  - *base
"""
    with pytest.raises(SchemaError) as exc_info:
        load_schema(text)
    assert "âncoras/aliases não são permitidos" in str(exc_info.value)


def test_rejeita_tag_customizada() -> None:
    text = """
version: !!python/object/apply:builtins.int [1]
tables: []
"""
    with pytest.raises(SchemaError):
        load_schema(text)


def test_rejeita_arquivo_maior_que_1_mib() -> None:
    padding = "x" * (MAX_FILE_SIZE_BYTES + 1)
    text = f"# {padding}\nversion: 1\ntables: []\n"
    with pytest.raises(SchemaError) as exc_info:
        load_schema(text)
    assert "excede o limite" in str(exc_info.value)


def test_rejeita_profundidade_maior_que_20() -> None:
    node: dict[str, object] = {"leaf": True}
    for _ in range(MAX_DEPTH + 5):
        node = {"nested": node}
    doc = _minimal_doc()
    doc["tables"][0]["columns"][0]["params"] = node  # type: ignore[index]
    with pytest.raises(SchemaError) as exc_info:
        load_schema(doc)
    assert "profundidade" in str(exc_info.value)


def test_rejeita_201_tabelas() -> None:
    doc = _minimal_doc(tables=[_minimal_table(i) for i in range(MAX_TABLES + 1)])
    with pytest.raises(SchemaError) as exc_info:
        load_schema(doc)
    assert any(e.path == "tables" for e in exc_info.value.errors)


def test_rejeita_501_colunas() -> None:
    table = _minimal_table()
    table["columns"] = [{"name": f"c{i}", "type": "int"} for i in range(MAX_COLUMNS_PER_TABLE + 1)]
    doc = _minimal_doc(tables=[table])
    with pytest.raises(SchemaError) as exc_info:
        load_schema(doc)
    assert any(e.path == "tables[0].columns" for e in exc_info.value.errors)


def test_rejeita_params_maior_que_64_kib() -> None:
    table = _minimal_table()
    table["columns"][0]["params"] = {"blob": "x" * (MAX_PARAMS_BYTES + 1)}  # type: ignore[index]
    doc = _minimal_doc(tables=[table])
    with pytest.raises(SchemaError) as exc_info:
        load_schema(doc)
    assert any(e.path == "tables[0].columns[0].params" for e in exc_info.value.errors)


def test_versao_diferente_de_1_e_rejeitada() -> None:
    with pytest.raises(SchemaError) as exc_info:
        load_schema(_minimal_doc(version=2))
    assert any("version" in e.path for e in exc_info.value.errors)


def test_erros_sao_acumulados_por_camada_com_caminho_correto() -> None:
    doc = _minimal_doc(tables=[_minimal_table(i) for i in range(MAX_TABLES + 1)])
    table = doc["tables"][0]  # type: ignore[index]
    table["columns"][0]["params"] = {"blob": "x" * (MAX_PARAMS_BYTES + 1)}  # type: ignore[index]
    with pytest.raises(SchemaError) as exc_info:
        load_schema(doc)
    paths = {e.path for e in exc_info.value.errors}
    assert "tables" in paths
    assert "tables[0].columns[0].params" in paths


def test_erros_estruturais_sao_acumulados_pela_camada_2() -> None:
    doc = _minimal_doc()
    doc["tables"][0]["rows"] = -5  # type: ignore[index]
    doc["tables"][0]["columns"][0]["null_ratio"] = 2.0  # type: ignore[index]
    with pytest.raises(SchemaError) as exc_info:
        load_schema(doc)
    assert len(exc_info.value.errors) >= 2


def test_rejeita_ancora_mesmo_sem_alias_correspondente() -> None:
    text = """
version: 1
tables:
  - &t
    name: t
    rows: 10
    primary_key: {columns: [id], strategy: sequence}
    columns:
      - {name: id, type: int}
"""
    with pytest.raises(SchemaError) as exc_info:
        load_schema(text)
    assert "âncoras/aliases não são permitidos" in str(exc_info.value)


def test_documento_raiz_precisa_ser_um_mapeamento() -> None:
    with pytest.raises(SchemaError) as exc_info:
        load_schema("- 1\n- 2\n- 3\n")
    assert any("mapeamento" in e.message for e in exc_info.value.errors)


def test_tabela_que_nao_e_mapeamento_e_ignorada_pelo_limite_de_colunas() -> None:
    doc = _minimal_doc(tables=["nao-e-um-dict"])
    # A camada 1 não quebra com uma tabela malformada; a camada 2 (Pydantic) reporta o erro.
    with pytest.raises(SchemaError):
        load_schema(doc)


def test_colunas_que_nao_sao_lista_sao_ignoradas_pelo_limite_de_colunas() -> None:
    table = _minimal_table()
    table["columns"] = "nao-e-uma-lista"
    doc = _minimal_doc(tables=[table])
    with pytest.raises(SchemaError):
        load_schema(doc)


# --- segredos ----------------------------------------------------------------


def test_rejeita_api_key_em_texto_claro_com_caminho_e_sugestao() -> None:
    doc = _minimal_doc(
        llm={
            "default_provider": "nuvem",
            "providers": {"nuvem": {"kind": "anthropic", "model": "x", "api_key": "sk-123"}},
        }
    )
    with pytest.raises(SchemaError) as exc_info:
        load_schema(doc)
    error = next(e for e in exc_info.value.errors if e.path == "llm.providers.nuvem.api_key")
    assert "api_key_env" in error.message
    assert "sk-123" not in error.message
    assert "sk-123" not in str(exc_info.value)


@pytest.mark.parametrize("secret_field", ["password", "token"])
def test_rejeita_password_e_token_em_qualquer_lugar(secret_field: str) -> None:
    doc = _minimal_doc()
    doc["tables"][0]["columns"][0]["params"] = {secret_field: "segredo"}  # type: ignore[index]
    with pytest.raises(SchemaError) as exc_info:
        load_schema(doc)
    assert any(secret_field in e.path for e in exc_info.value.errors)


# --- validate() (camadas 3 e 4) ----------------------------------------------


def test_validate_sem_ctx_e_valido() -> None:
    schema = load_schema(_minimal_doc())
    report = validate(schema)
    assert report.is_valid
    assert report.errors == []


def test_validate_com_ctx_reporta_erros_sem_lancar() -> None:
    schema = load_schema(_minimal_doc())
    report = validate(schema, ValidationContext(generators={}))
    assert not report.is_valid
    assert report.errors
