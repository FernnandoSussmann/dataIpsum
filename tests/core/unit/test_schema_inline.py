"""Testes de flags inline (DD-00 §7.1: schema/inline.py)."""

from __future__ import annotations

import pytest

from dataipsum.errors import SchemaError
from dataipsum.schema.inline import build_inline_schema


def test_id_int_pk() -> None:
    schema = build_inline_schema("t", 10, ["id:int:pk"])
    table = schema.tables[0]
    assert table.name == "t"
    assert table.rows == 10
    assert table.primary_key.columns == ["id"]
    assert table.columns[0].type == "int"


def test_nome_nome_proprio() -> None:
    schema = build_inline_schema("t", 10, ["id:int:pk", "nome:nome_proprio"])
    nome = schema.tables[0].columns[1]
    assert nome.name == "nome"
    assert nome.type == "nome_proprio"


def test_bio_string_max_length() -> None:
    schema = build_inline_schema("t", 10, ["id:int:pk", "bio:string:max_length=50"])
    bio = schema.tables[0].columns[1]
    assert bio.max_length == 50
    assert bio.params == {}


def test_chave_desconhecida_vai_para_params() -> None:
    schema = build_inline_schema(
        "t", 10, ["id:int:pk", "cpf:cpf:format=masked", "x:tipo:regiao=sul"]
    )
    coluna = schema.tables[0].columns[2]
    assert coluna.params == {"regiao": "sul"}


def test_sem_coluna_pk_usa_a_primeira_coluna() -> None:
    schema = build_inline_schema("t", 10, ["id:int", "nome:nome_proprio"])
    assert schema.tables[0].primary_key.columns == ["id"]


def test_tipo_inexistente_sem_dois_pontos() -> None:
    with pytest.raises(SchemaError) as exc_info:
        build_inline_schema("t", 10, ["nome"])
    assert exc_info.value.errors[0].path == "cols[0]"


def test_tipo_inexistente_com_dois_pontos_vazio() -> None:
    with pytest.raises(SchemaError):
        build_inline_schema("t", 10, ["nome:"])


def test_chave_de_parametro_vazia() -> None:
    with pytest.raises(SchemaError) as exc_info:
        build_inline_schema("t", 10, ["id:int:pk", "bio:string:=50"])
    assert "vazia" in exc_info.value.errors[0].message


def test_chave_de_parametro_invalida() -> None:
    with pytest.raises(SchemaError) as exc_info:
        build_inline_schema("t", 10, ["id:int:pk", "bio:string:xyz"])
    assert "chave=valor" in exc_info.value.errors[0].message


def test_mais_de_uma_coluna_pk() -> None:
    with pytest.raises(SchemaError) as exc_info:
        build_inline_schema("t", 10, ["id:int:pk", "codigo:int:pk"])
    assert any("pk" in e.message for e in exc_info.value.errors)


def test_sem_nenhuma_coluna_e_invalido() -> None:
    with pytest.raises(SchemaError):
        build_inline_schema("t", 10, [])


def test_erros_de_varias_colunas_sao_acumulados() -> None:
    with pytest.raises(SchemaError) as exc_info:
        build_inline_schema("t", 10, ["nome", "bio:string:xyz"])
    assert len(exc_info.value.errors) == 2
