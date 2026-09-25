"""Testes de `import_ddl` (DD-02 §F.3.4, §F.5, §F.6)."""

from __future__ import annotations

import sys

import pytest

from dataipsum.errors import SchemaError
from dataipsum.schema_io import ImportReport, import_ddl
from dataipsum.schema_io.ddl_import import MAX_IMPORT_SQL_BYTES


def _column(schema_dict: dict[str, object], table_name: str, column_name: str) -> dict[str, object]:
    tables = schema_dict["tables"]
    assert isinstance(tables, list)
    table = next(t for t in tables if t["name"] == table_name)
    columns = table["columns"]
    return next(c for c in columns if c["name"] == column_name)


def _table(schema_dict: dict[str, object], table_name: str) -> dict[str, object]:
    tables = schema_dict["tables"]
    assert isinstance(tables, list)
    return next(t for t in tables if t["name"] == table_name)


def test_never_imports_driver_modules() -> None:
    for driver in ("psycopg", "pymysql", "PyMySQL"):
        assert driver not in sys.modules
    import_ddl("CREATE TABLE t (id SERIAL PRIMARY KEY)", "postgres")
    for driver in ("psycopg", "pymysql"):
        assert driver not in sys.modules


def test_sql_maior_que_limite_e_erro() -> None:
    huge_sql = "CREATE TABLE t (id INT); -- " + ("x" * (MAX_IMPORT_SQL_BYTES + 1))
    with pytest.raises(SchemaError):
        import_ddl(huge_sql, "postgres")


def test_apenas_create_e_alter_sao_considerados() -> None:
    sql = """
    CREATE TABLE clientes (id SERIAL PRIMARY KEY);
    INSERT INTO clientes (id) VALUES (1);
    CREATE INDEX idx_id ON clientes (id);
    DROP TABLE outra;
    """
    schema, report = import_ddl(sql, "postgres")
    assert len(schema.tables) == 1
    assert any("Insert" in finding for finding in report.findings)
    assert any("Create" in finding or "Drop" in finding for finding in report.findings)


def test_bloco_revise_e_relatorio_por_stderr_compativel() -> None:
    schema, report = import_ddl(
        "CREATE TABLE clientes (id SERIAL PRIMARY KEY, cpf CHAR(11) NOT NULL)", "postgres"
    )
    assert isinstance(report, ImportReport)
    block = report.render_yaml_comment_block()
    assert block.startswith("# Revise:\n")


@pytest.mark.parametrize(
    ("sql_type", "expected_type", "expected_max_length"),
    [
        ("VARCHAR(120)", "string", 120),
        ("CHAR(5)", "char", 5),
        ("REAL", "float", None),
        ("DOUBLE", "float", None),
        ("BOOLEAN", "boolean", None),
        ("DATE", "date", None),
        ("TIME", "time", None),
        ("TIMESTAMP", "timestamp", None),
        ("UUID", "uuid", None),
    ],
)
def test_mapeamento_de_tipos_sql(
    sql_type: str, expected_type: str, expected_max_length: int | None
) -> None:
    sql = f"CREATE TABLE t (id SERIAL PRIMARY KEY, campo_x {sql_type})"
    schema, _ = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    column = _column(document, "t", "campo_x")
    assert column["type"] == expected_type
    if expected_max_length is not None:
        assert column["max_length"] == expected_max_length


def test_varchar_sem_tamanho_vira_string_255_com_todo() -> None:
    schema, report = import_ddl("CREATE TABLE t (id SERIAL PRIMARY KEY, obs VARCHAR)", "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    column = _column(document, "t", "obs")
    assert column["type"] == "string"
    assert column["max_length"] == 255
    assert any("VARCHAR sem tamanho" in finding for finding in report.findings)


def test_tipo_desconhecido_vira_string_com_aviso() -> None:
    schema, report = import_ddl("CREATE TABLE t (id SERIAL PRIMARY KEY, geo POINT)", "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    column = _column(document, "t", "geo")
    assert column["type"] == "string"
    assert column["max_length"] == 255
    assert any("desconhecido" in finding for finding in report.findings)


def test_decimal_extrai_precisao_e_escala() -> None:
    schema, _ = import_ddl(
        "CREATE TABLE t (id SERIAL PRIMARY KEY, preco DECIMAL(8, 3))", "postgres"
    )
    document = schema.model_dump(mode="json", exclude_none=True)
    column = _column(document, "t", "preco")
    assert column["type"] == "decimal"
    assert column["params"] == {"precision": 8, "scale": 3}


def test_timestamptz_recebe_timezone_true() -> None:
    schema, _ = import_ddl("CREATE TABLE t (id SERIAL PRIMARY KEY, criado TIMESTAMPTZ)", "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    column = _column(document, "t", "criado")
    assert column["type"] == "timestamp"
    assert column["params"] == {"timezone": True}


def test_json_recebe_params_de_exemplo_com_todo() -> None:
    schema, report = import_ddl("CREATE TABLE t (id SERIAL PRIMARY KEY, dados JSONB)", "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    column = _column(document, "t", "dados")
    assert column["type"] == "json"
    assert column["params"] == {"exemplo": {"valor": "TODO"}}
    assert any("JSON" in finding for finding in report.findings)


def test_serial_vira_pk_sequence() -> None:
    schema, _ = import_ddl("CREATE TABLE t (id SERIAL PRIMARY KEY)", "postgres")
    assert schema.tables[0].primary_key.strategy == "sequence"


def test_pk_uuid_vira_seeded_uuid() -> None:
    schema, _ = import_ddl("CREATE TABLE t (id UUID PRIMARY KEY)", "postgres")
    assert schema.tables[0].primary_key.strategy == "seeded_uuid"


def test_pk_textual_e_erro_com_sugestao() -> None:
    with pytest.raises(SchemaError, match="chave primária textual"):
        import_ddl("CREATE TABLE t (codigo VARCHAR(10) PRIMARY KEY)", "postgres")


def test_pk_composta_generica_e_erro() -> None:
    sql = "CREATE TABLE t (a INT NOT NULL, b INT NOT NULL, PRIMARY KEY (a, b))"
    with pytest.raises(SchemaError):
        import_ddl(sql, "postgres")


def test_ponte_com_2_fks_vira_many_to_many() -> None:
    sql = """
    CREATE TABLE lojas (id SERIAL PRIMARY KEY);
    CREATE TABLE categorias (id SERIAL PRIMARY KEY);
    CREATE TABLE loja_categoria (
      loja_id INT NOT NULL,
      categoria_id INT NOT NULL,
      PRIMARY KEY (loja_id, categoria_id),
      FOREIGN KEY (loja_id) REFERENCES lojas(id),
      FOREIGN KEY (categoria_id) REFERENCES categorias(id)
    );
    """
    schema, _ = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    bridge = _table(document, "loja_categoria")
    assert bridge["primary_key"]["strategy"] == "composite"
    assert bridge["rows_from"]["relation"] == "many_to_many"
    assert bridge["rows_from"]["via"] == "loja_id"
    assert bridge["rows_from"]["pair"] == "categoria_id"


def test_fk_unique_vira_one_to_one() -> None:
    sql = """
    CREATE TABLE usuarios (id SERIAL PRIMARY KEY);
    CREATE TABLE perfis (
      id SERIAL PRIMARY KEY,
      usuario_id INT NOT NULL UNIQUE REFERENCES usuarios(id)
    );
    """
    schema, _ = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    perfis = _table(document, "perfis")
    assert perfis["rows_from"]["relation"] == "one_to_one"
    assert perfis["rows_from"]["coverage"] == 1.0


def test_fk_simples_vira_one_to_many() -> None:
    sql = """
    CREATE TABLE usuarios (id SERIAL PRIMARY KEY);
    CREATE TABLE pedidos (
      id SERIAL PRIMARY KEY,
      usuario_id INT NOT NULL REFERENCES usuarios(id)
    );
    """
    schema, _ = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    pedidos = _table(document, "pedidos")
    assert pedidos["rows_from"]["relation"] == "one_to_many"
    assert pedidos["rows_from"]["cardinality"] == {"range": {"min": 0, "max": 5}}
    usuario_id_column = _column(document, "pedidos", "usuario_id")
    assert usuario_id_column["type"] == "ref"
    assert usuario_id_column["params"] == {"table": "usuarios"}


def test_tabela_sem_fk_e_raiz_com_1000_linhas() -> None:
    schema, _ = import_ddl("CREATE TABLE t (id SERIAL PRIMARY KEY)", "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    assert _table(document, "t")["rows"] == 1000


def test_auto_fk_vira_coluna_simples_com_aviso() -> None:
    sql = """
    CREATE TABLE funcionarios (
      id SERIAL PRIMARY KEY,
      gerente_id INT REFERENCES funcionarios(id)
    );
    """
    schema, report = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    gerente_id_column = _column(document, "funcionarios", "gerente_id")
    assert gerente_id_column["type"] == "int"
    assert "rows_from" not in _table(document, "funcionarios")
    assert any("auto-FK" in finding for finding in report.findings)


def test_ciclo_entre_tabelas_e_erro() -> None:
    sql = """
    CREATE TABLE a (id SERIAL PRIMARY KEY, b_id INT REFERENCES b(id));
    CREATE TABLE b (id SERIAL PRIMARY KEY, a_id INT REFERENCES a(id));
    """
    with pytest.raises(SchemaError, match="ciclo"):
        import_ddl(sql, "postgres")


def test_alter_table_add_foreign_key_e_considerado() -> None:
    sql = """
    CREATE TABLE usuarios (id SERIAL PRIMARY KEY);
    CREATE TABLE pedidos (id SERIAL PRIMARY KEY, usuario_id INT NOT NULL);
    ALTER TABLE pedidos ADD CONSTRAINT fk_usuario FOREIGN KEY (usuario_id) REFERENCES usuarios (id);
    """
    schema, _ = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    pedidos = _table(document, "pedidos")
    assert pedidos["rows_from"]["via"] == "usuario_id"


@pytest.mark.parametrize(
    ("column_name", "declared_type", "expected_type", "expected_extra"),
    [
        ("cpf", "CHAR(11) NOT NULL", "cpf", {"format": "unmasked"}),
        ("cpf", "CHAR(14) NOT NULL", "cpf", {"format": "masked"}),
        ("rg", "VARCHAR(12)", "rg", {}),
        ("numero_cartao", "VARCHAR(19)", "cartao_credito", {}),
        ("nome_completo", "VARCHAR(120)", "nome_proprio", {}),
        ("post", "TEXT", "llm_post", {}),
        ("texto_contrato", "TEXT", "llm_contrato", {}),
    ],
)
def test_inferencia_por_nome(
    column_name: str, declared_type: str, expected_type: str, expected_extra: dict[str, object]
) -> None:
    sql = f"CREATE TABLE t (id SERIAL PRIMARY KEY, {column_name} {declared_type})"
    schema, _ = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    column = _column(document, "t", column_name)
    assert column["type"] == expected_type
    for key, value in expected_extra.items():
        assert column[key] == value


def test_colunas_nao_textuais_nunca_sao_inferidas() -> None:
    schema, _ = import_ddl("CREATE TABLE t (id SERIAL PRIMARY KEY, nome INT)", "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    assert _column(document, "t", "nome")["type"] == "int"


def test_email_usa_max_length_do_varchar_e_name_column() -> None:
    sql = "CREATE TABLE t (id SERIAL PRIMARY KEY, nome VARCHAR(80), email VARCHAR(120))"
    schema, _ = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    email_column = _column(document, "t", "email")
    assert email_column["type"] == "email"
    assert email_column["max_length"] == 120
    assert email_column["params"] == {"name_column": "nome"}


def test_email_max_length_e_limitado_a_254() -> None:
    sql = "CREATE TABLE t (id SERIAL PRIMARY KEY, email VARCHAR(500))"
    schema, _ = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    assert _column(document, "t", "email")["max_length"] == 254


def test_llm_email_nunca_e_inferido() -> None:
    sql = "CREATE TABLE t (id SERIAL PRIMARY KEY, corpo_llm_email TEXT)"
    schema, _ = import_ddl(sql, "postgres")
    document = schema.model_dump(mode="json", exclude_none=True)
    assert _column(document, "t", "corpo_llm_email")["type"] != "llm_email"


def test_llm_inferido_recebe_secao_llm_placeholder() -> None:
    schema, report = import_ddl("CREATE TABLE t (id SERIAL PRIMARY KEY, post TEXT)", "postgres")
    assert schema.llm is not None
    assert schema.llm.default_provider == "local"
    assert any("llm" in finding.lower() for finding in report.findings)


def test_normalizacao_de_identificador_invalido() -> None:
    sql = 'CREATE TABLE "Clientes" ("Id" SERIAL PRIMARY KEY)'
    schema, report = import_ddl(sql, "postgres")
    assert schema.tables[0].name == "clientes"
    assert schema.tables[0].columns[0].name == "id"
    assert any("normalizada" in finding for finding in report.findings)


def test_colisao_apos_normalizacao_e_erro() -> None:
    sql = 'CREATE TABLE t ("Id" SERIAL PRIMARY KEY, "id" INT)'
    with pytest.raises(SchemaError, match="colisão"):
        import_ddl(sql, "postgres")


def test_mais_de_200_tabelas_e_erro() -> None:
    sql = "".join(f"CREATE TABLE t{i} (id SERIAL PRIMARY KEY);" for i in range(201))
    with pytest.raises(SchemaError):
        import_ddl(sql, "postgres")


def test_mais_de_500_colunas_e_erro() -> None:
    columns_sql = ", ".join(f"c{i} INT" for i in range(500))
    sql = f"CREATE TABLE t (id SERIAL PRIMARY KEY, {columns_sql})"
    with pytest.raises(SchemaError):
        import_ddl(sql, "postgres")
