"""Testes do parser restrito de templates e do `TemplateValidator` (DD-01 §C.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataipsum.errors import SchemaError
from dataipsum.llm.template import (
    TemplateSyntaxError,
    TemplateValidator,
    Var,
    extract_markers,
    fill_pool_text,
    parse_template,
    render,
    unknown_markers,
)
from dataipsum.schema.models import (
    ColumnSpec,
    LLMConfig,
    LLMProviderConfig,
    PrimaryKeySpec,
    RowsFromSpec,
    Schema,
    TableSpec,
)

_LLM_CONFIG = LLMConfig(
    default_provider="local",
    providers={"local": LLMProviderConfig(kind="ollama", model="llama3.1:8b")},
)


def _schema_with_parent_child() -> tuple[Schema, TableSpec, TableSpec]:
    usuarios = TableSpec(
        name="usuarios",
        rows=10,
        primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
        columns=[
            ColumnSpec(name="id", type="int"),
            ColumnSpec(name="nome", type="nome_proprio"),
            ColumnSpec(name="bio", type="llm_post"),
        ],
    )
    posts = TableSpec(
        name="posts",
        primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
        rows_from=RowsFromSpec(via="autor_id", relation="one_to_many"),
        columns=[
            ColumnSpec(name="id", type="int"),
            ColumnSpec(name="autor_id", type="ref", params={"table": "usuarios"}),
            ColumnSpec(name="titulo", type="string", max_length=80),
            ColumnSpec(name="conteudo", type="llm_post", max_length=280),
        ],
    )
    schema = Schema(version=1, tables=[usuarios, posts], llm=_LLM_CONFIG)
    return schema, usuarios, posts


# --- parser ---------------------------------------------------------------


def test_parse_literal_e_variaveis() -> None:
    tokens = parse_template("Post de {autor_id.nome} sobre {titulo}!")
    assert tokens == (
        "Post de ",
        Var(("autor_id", "nome")),
        " sobre ",
        Var(("titulo",)),
        "!",
    )


def test_parse_chaves_literais() -> None:
    tokens = parse_template('JSON: {{"a": 1}} e {coluna}')
    assert tokens[0] == 'JSON: {"a": 1} e '
    assert tokens[1] == Var(("coluna",))


def test_parse_ref_sozinho_e_valido_sintaticamente() -> None:
    # `{ref}` sozinho é sintaticamente válido; é rejeitado na VALIDAÇÃO semântica (chave).
    assert parse_template("{autor_id}") == (Var(("autor_id",)),)


def test_parse_a_b_c_e_rejeitado() -> None:
    with pytest.raises(TemplateSyntaxError):
        parse_template("{a.b.c}")


def test_parse_chave_sem_fechamento_e_rejeitada() -> None:
    with pytest.raises(TemplateSyntaxError):
        parse_template("texto {aberto")


def test_parse_chave_de_fechamento_sem_abertura_e_rejeitada() -> None:
    with pytest.raises(TemplateSyntaxError):
        parse_template("texto } solto")


def test_parse_nao_usa_str_format() -> None:
    """Teste de arquitetura: nenhum código (fora de docstring/comentário) usa `.format(`,
    `eval(` ou importa Jinja."""
    import ast

    package_root = Path(__file__).resolve().parents[3] / "src" / "dataipsum" / "llm"
    offenders: dict[str, list[str]] = {}
    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found = [
            node.func.attr
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            else "eval"
            for node in ast.walk(tree)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"
            )
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "eval"
            )
            or isinstance(node, ast.Import | ast.ImportFrom)
            and any("jinja" in (alias.name or "").lower() for alias in node.names)
        ]
        if found:
            offenders[str(path)] = found
    assert not offenders, offenders


# --- render -----------------------------------------------------------------


def test_render_substitui_e_normaliza_quebras_de_linha() -> None:
    tokens = parse_template("Ola {nome}!")
    text = render(tokens, same_row={"nome": "Ana\r\nSilva"}, parent_values={})
    assert text == "Ola Ana\nSilva!"


def test_render_trunca_valor_em_500_caracteres() -> None:
    tokens = parse_template("{nome}")
    text = render(tokens, same_row={"nome": "x" * 600}, parent_values={})
    assert len(text) == 500


def test_render_trunca_prompt_total_em_16kib() -> None:
    tokens = parse_template("{nome}")
    text = render(tokens, same_row={"nome": "y" * 100}, parent_values={})
    tokens_grandes = ("z" * 20_000,)
    resultado = render(tokens_grandes, same_row={}, parent_values={})
    assert len(resultado.encode("utf-8")) <= 16 * 1024
    assert text == "y" * 100


def test_render_navega_ate_o_pai() -> None:
    tokens = parse_template("Post de {autor_id.nome}")
    text = render(tokens, same_row={}, parent_values={"autor_id": {"nome": "Fernanda"}})
    assert text == "Post de Fernanda"


# --- extract_markers / unknown_markers / fill_pool_text ---------------------


def test_extract_markers_ignora_chaves_malformadas() -> None:
    markers = extract_markers("{{literal}} {valido} {inv@lido} {a.b.c}")
    assert markers == (Var(("valido",)),)


def test_unknown_markers_detecta_marcador_fora_do_template() -> None:
    valid = (Var(("nome",)),)
    assert unknown_markers("Ola {nome}, veja {outra}", valid) == (Var(("outra",)),)
    assert unknown_markers("Ola {nome}!", valid) == ()


def test_fill_pool_text_preenche_so_marcadores_conhecidos() -> None:
    filled = fill_pool_text(
        "Ola {nome}, seu pedido {pedido_id.status} chegou. {{literal}}",
        same_row={"nome": "Ana"},
        parent_values={"pedido_id": {"status": "enviado"}},
    )
    assert filled == "Ola Ana, seu pedido enviado chegou. {literal}"


# --- TemplateValidator --------------------------------------------------


def test_validator_aceita_referencia_ao_pai_por_coluna_deterministica() -> None:
    schema, _usuarios, posts = _schema_with_parent_child()
    posts_titulo_column = next(c for c in posts.columns if c.name == "titulo")
    variables = TemplateValidator().validate(
        schema, posts, posts_titulo_column, "Post de {autor_id.nome} sobre {titulo}"
    )
    assert set(variables) == {Var(("autor_id", "nome")), Var(("titulo",))}


def test_validator_rejeita_ref_sozinho() -> None:
    schema, _usuarios, posts = _schema_with_parent_child()
    column = next(c for c in posts.columns if c.name == "conteudo")
    with pytest.raises(SchemaError):
        TemplateValidator().validate(schema, posts, column, "Pedido {autor_id}")


def test_validator_rejeita_pk_da_propria_tabela() -> None:
    schema, _usuarios, posts = _schema_with_parent_child()
    column = next(c for c in posts.columns if c.name == "conteudo")
    with pytest.raises(SchemaError):
        TemplateValidator().validate(schema, posts, column, "Post numero {id}")


def test_validator_rejeita_pk_do_pai() -> None:
    schema, _usuarios, posts = _schema_with_parent_child()
    column = next(c for c in posts.columns if c.name == "conteudo")
    with pytest.raises(SchemaError):
        TemplateValidator().validate(schema, posts, column, "Post de {autor_id.id}")


def test_validator_rejeita_outra_ref_do_pai() -> None:
    schema, usuarios, posts = _schema_with_parent_child()
    usuarios_com_ref = usuarios.model_copy(
        update={
            "columns": [
                *usuarios.columns,
                ColumnSpec(name="empresa_id", type="ref", params={"table": "usuarios"}),
            ]
        }
    )
    schema = schema.model_copy(update={"tables": [usuarios_com_ref, posts]})
    column = next(c for c in posts.columns if c.name == "conteudo")
    with pytest.raises(SchemaError):
        TemplateValidator().validate(schema, posts, column, "Empresa {autor_id.empresa_id}")


def test_validator_rejeita_variavel_inexistente() -> None:
    schema, _usuarios, posts = _schema_with_parent_child()
    column = next(c for c in posts.columns if c.name == "conteudo")
    with pytest.raises(SchemaError):
        TemplateValidator().validate(schema, posts, column, "{coluna_que_nao_existe}")


def test_validator_rejeita_coluna_llm_do_pai() -> None:
    schema, _usuarios, posts = _schema_with_parent_child()
    column = next(c for c in posts.columns if c.name == "conteudo")
    with pytest.raises(SchemaError):
        TemplateValidator().validate(schema, posts, column, "Bio do autor: {autor_id.bio}")


def test_validator_rejeita_coluna_llm_da_mesma_linha() -> None:
    schema, _usuarios, posts = _schema_with_parent_child()
    posts_com_duas_llm = posts.model_copy(
        update={
            "columns": [
                *posts.columns,
                ColumnSpec(name="resumo", type="llm_post"),
            ]
        }
    )
    schema = schema.model_copy(update={"tables": [schema.tables[0], posts_com_duas_llm]})
    resumo_column = next(c for c in posts_com_duas_llm.columns if c.name == "resumo")
    conteudo_column = next(c for c in posts_com_duas_llm.columns if c.name == "conteudo")
    with pytest.raises(SchemaError):
        TemplateValidator().validate(
            schema, posts_com_duas_llm, resumo_column, "Resumo de {conteudo}"
        )
    # Sanity: a própria coluna não gera erro por causa de OUTRA coisa.
    assert conteudo_column.type == "llm_post"


def test_validator_a_b_c_e_rejeitado() -> None:
    schema, _usuarios, posts = _schema_with_parent_child()
    column = next(c for c in posts.columns if c.name == "conteudo")
    with pytest.raises(SchemaError):
        TemplateValidator().validate(schema, posts, column, "{autor_id.nome.sobrenome}")
