"""Testes do modelo Pydantic do schema (DD-00 §7.1: schema/models.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from dataipsum.errors import SchemaError
from dataipsum.schema.models import (
    CardinalityRange,
    ColumnSpec,
    LLMConfig,
    LLMProviderConfig,
    PrimaryKeySpec,
    RowsFromSpec,
    Schema,
    TableSpec,
    ValidationContext,
    effective_locale,
    normalize_schema,
    validate_with_registry,
)


def _column(name: str, type_: str, **kwargs: object) -> ColumnSpec:
    return ColumnSpec(name=name, type=type_, **kwargs)


def _table(name: str, columns: list[ColumnSpec], **kwargs: object) -> TableSpec:
    kwargs.setdefault("rows", 10)
    kwargs.setdefault("primary_key", PrimaryKeySpec(columns=[columns[0].name], strategy="sequence"))
    return TableSpec(name=name, columns=columns, **kwargs)


def _schema(tables: list[TableSpec], **kwargs: object) -> Schema:
    return Schema(version=1, tables=tables, **kwargs)


class FakeGenerator:
    """Fake mínimo: só os membros usados por `validate_with_registry`/`normalize_schema`."""

    def __init__(
        self,
        *,
        supports_invalid: bool = False,
        supports_format: bool = False,
        params_errors: list[object] | None = None,
        depends_on_columns: list[str] | None = None,
        implied: list[ColumnSpec] | None = None,
    ) -> None:
        self.supports_invalid = supports_invalid
        self.supports_format = supports_format
        self._params_errors = params_errors or []
        self._depends_on_columns = depends_on_columns or []
        self._implied = implied or []

    def validate_params(self, column: object, ctx: object) -> list[object]:
        return self._params_errors

    def depends_on(self, column: object) -> list[str]:
        return self._depends_on_columns

    def implied_columns(self, column: object) -> list[ColumnSpec]:
        return self._implied


class FakePlanner:
    def __init__(self, implied: list[ColumnSpec] | None = None) -> None:
        self._implied = implied or []

    def validate(self, schema: object) -> list[object]:
        return []

    def implied_columns(self, table: object) -> list[ColumnSpec]:
        return self._implied


# --- identificadores -------------------------------------------------------


@pytest.mark.parametrize("name", ["Usuarios", "../x", "1col", "a" * 64])
def test_identificador_invalido_gera_erro(name: str) -> None:
    with pytest.raises(PydanticValidationError):
        _table(name, [_column("id", "int")])


def test_identificador_de_64_caracteres_e_invalido_mas_63_e_valido() -> None:
    _table("a" * 63, [_column("id", "int")])
    with pytest.raises(PydanticValidationError):
        _table("a" * 64, [_column("id", "int")])


# --- rows / rows_from --------------------------------------------------------


def test_rows_e_rows_from_sao_mutuamente_exclusivos() -> None:
    with pytest.raises(PydanticValidationError, match="mutuamente exclusivos"):
        TableSpec(
            name="t",
            rows=10,
            rows_from=RowsFromSpec(via="usuario_id", relation="one_to_many"),
            primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
            columns=[_column("id", "int")],
        )


def test_tabela_sem_rows_e_sem_rows_from_e_invalida() -> None:
    with pytest.raises(PydanticValidationError):
        TableSpec(
            name="t",
            primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
            columns=[_column("id", "int")],
        )


def test_tabela_filha_com_rows_from_e_valida() -> None:
    table = TableSpec(
        name="pedidos",
        rows_from=RowsFromSpec(via="usuario_id", relation="one_to_many"),
        primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
        columns=[_column("id", "int")],
    )
    assert table.rows is None


def test_composite_so_e_valido_em_many_to_many() -> None:
    with pytest.raises(PydanticValidationError, match="composite"):
        TableSpec(
            name="t",
            rows_from=RowsFromSpec(via="usuario_id", relation="one_to_many"),
            primary_key=PrimaryKeySpec(columns=["id"], strategy="composite"),
            columns=[_column("id", "int")],
        )


def test_cardinality_range_min_maior_que_max_e_invalido() -> None:
    with pytest.raises(PydanticValidationError, match="min"):
        CardinalityRange(min=5, max=1)


# --- null_ratio == 0 em PK e na coluna `via` (§3.3) -------------------------


def test_null_ratio_diferente_de_zero_em_coluna_de_pk_e_invalido() -> None:
    with pytest.raises(PydanticValidationError, match="chave primária"):
        TableSpec(
            name="t",
            rows=10,
            primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
            columns=[_column("id", "int", null_ratio=0.1)],
        )


def test_null_ratio_zero_em_coluna_de_pk_e_valido() -> None:
    _table("t", [_column("id", "int", null_ratio=0.0)])


def test_null_ratio_diferente_de_zero_na_coluna_via_e_invalido() -> None:
    with pytest.raises(PydanticValidationError, match="via"):
        TableSpec(
            name="pedidos",
            rows_from=RowsFromSpec(via="usuario_id", relation="one_to_many"),
            primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
            columns=[
                _column("id", "int"),
                _column("usuario_id", "ref", null_ratio=0.2, params={"table": "usuarios"}),
            ],
        )


def test_null_ratio_zero_na_coluna_via_e_valido() -> None:
    TableSpec(
        name="pedidos",
        rows_from=RowsFromSpec(via="usuario_id", relation="one_to_many"),
        primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
        columns=[
            _column("id", "int"),
            _column("usuario_id", "ref", params={"table": "usuarios"}),
        ],
    )


def test_thread_so_e_valido_com_relation_thread() -> None:
    with pytest.raises(PydanticValidationError, match="thread"):
        TableSpec(
            name="t",
            rows_from=RowsFromSpec(via="usuario_id", relation="one_to_many"),
            thread={"seq": "seq"},
            primary_key=PrimaryKeySpec(columns=["id"], strategy="sequence"),
            columns=[_column("id", "int")],
        )


# --- null_ratio / invalid_ratio / format / max_length (estrutural) ----------


@pytest.mark.parametrize("field_name", ["null_ratio", "invalid_ratio"])
@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_ratio_fora_de_0_1_e_invalido(field_name: str, value: float) -> None:
    with pytest.raises(PydanticValidationError):
        _column("c", "string", max_length=10, **{field_name: value})


def test_max_length_menor_que_1_e_invalido() -> None:
    with pytest.raises(PydanticValidationError):
        _column("c", "string", max_length=0)


def test_nomes_de_coluna_duplicados_geram_erro() -> None:
    with pytest.raises(PydanticValidationError, match="duplicados"):
        _table("t", [_column("id", "int"), _column("id", "string", max_length=5)])


def test_nomes_de_tabela_duplicados_geram_erro() -> None:
    with pytest.raises(PydanticValidationError, match="duplicados"):
        _schema([_table("t", [_column("id", "int")]), _table("t", [_column("id", "int")])])


# --- segredos (api_key/password/token) --------------------------------------


@pytest.mark.parametrize("secret_field", ["api_key", "password", "token"])
def test_llm_provider_nao_aceita_campos_de_segredo_em_texto_claro(secret_field: str) -> None:
    with pytest.raises(PydanticValidationError):
        LLMProviderConfig(kind="anthropic", model="x", **{secret_field: "sk-123"})


def test_llm_provider_aceita_api_key_env() -> None:
    provider = LLMProviderConfig(kind="anthropic", model="x", api_key_env="ANTHROPIC_API_KEY")
    assert provider.api_key_env == "ANTHROPIC_API_KEY"


def test_llm_default_provider_precisa_existir_em_providers() -> None:
    with pytest.raises(PydanticValidationError, match="default_provider"):
        LLMConfig(
            default_provider="ausente",
            providers={"local": LLMProviderConfig(kind="ollama", model="m")},
        )


def test_coluna_llm_exige_secao_llm_no_schema() -> None:
    with pytest.raises(PydanticValidationError, match="llm"):
        _schema([_table("t", [_column("c", "llm_post", max_length=100)])])


def test_coluna_llm_com_secao_llm_e_valida() -> None:
    schema = _schema(
        [_table("t", [_column("c", "llm_post", max_length=100)])],
        llm=LLMConfig(
            default_provider="local",
            providers={"local": LLMProviderConfig(kind="ollama", model="m")},
        ),
    )
    assert schema.llm is not None


# --- effective_locale --------------------------------------------------------


def test_effective_locale_cai_em_cascata() -> None:
    column = _column("nome", "nome_proprio", max_length=120)
    table = _table("usuarios", [column])
    schema = _schema([table])
    assert effective_locale(schema, table, column) == "pt_BR"

    table_pt = table.model_copy(update={"locale": "en_US"})
    assert effective_locale(schema, table_pt, column) == "en_US"

    column_fr = column.model_copy(update={"locale": "fr_FR"})
    assert effective_locale(schema, table_pt, column_fr) == "fr_FR"


# --- validate_with_registry (camadas 3 e 4, delegadas ao registry) ---------


def test_validate_with_registry_sem_ctx_nao_gera_erros() -> None:
    schema = _schema([_table("t", [_column("id", "int")])])
    assert validate_with_registry(schema) == []


def test_tipo_desconhecido_gera_erro_de_camada_3() -> None:
    schema = _schema([_table("t", [_column("id", "int")])])
    ctx = ValidationContext(generators={})
    errors = validate_with_registry(schema, ctx)
    assert any("desconhecido" in e.message for e in errors)
    assert errors[0].path == "tables[0].columns[0].type"


def test_invalid_ratio_sem_supports_invalid_gera_erro() -> None:
    column = _column("nome", "nome_proprio", invalid_ratio=0.1)
    schema = _schema([_table("t", [column])])
    ctx = ValidationContext(generators={"nome_proprio": FakeGenerator(supports_invalid=False)})
    errors = validate_with_registry(schema, ctx)
    assert any(e.path == "tables[0].columns[0].invalid_ratio" for e in errors)


def test_invalid_ratio_com_supports_invalid_nao_gera_erro() -> None:
    column = _column("cpf", "cpf", invalid_ratio=0.1)
    schema = _schema([_table("t", [column])])
    ctx = ValidationContext(generators={"cpf": FakeGenerator(supports_invalid=True)})
    errors = validate_with_registry(schema, ctx)
    assert errors == []


def test_format_sem_supports_format_gera_erro() -> None:
    column = _column("cpf", "cpf", format="masked")
    schema = _schema([_table("t", [column])])
    ctx = ValidationContext(generators={"cpf": FakeGenerator(supports_format=False)})
    errors = validate_with_registry(schema, ctx)
    assert any(e.path == "tables[0].columns[0].format" for e in errors)


def test_max_length_ausente_em_string_e_delegado_ao_validate_params() -> None:
    from dataipsum.errors import ValidationError

    column = _column("bio", "string")

    class StringGenerator(FakeGenerator):
        def validate_params(self, column: object, ctx: object) -> list[object]:
            if getattr(column, "max_length", None) is None:
                return [ValidationError(path="max_length", message="obrigatório para 'string'")]
            return []

    schema = _schema([_table("t", [column])])
    ctx = ValidationContext(generators={"string": StringGenerator()})
    errors = validate_with_registry(schema, ctx)
    assert any(e.path == "tables[0].columns[0].params.max_length" for e in errors)


def test_depends_on_coluna_inexistente_gera_erro() -> None:
    column = _column("email", "email")
    schema = _schema([_table("t", [column])])
    ctx = ValidationContext(
        generators={"email": FakeGenerator(depends_on_columns=["nome_completo"])}
    )
    errors = validate_with_registry(schema, ctx)
    assert any("inexistente" in e.message for e in errors)


def test_depends_on_coluna_llm_gera_erro() -> None:
    comentario = _column("comentario", "llm_post", max_length=100)
    email = _column("email", "email")
    schema = _schema(
        [_table("t", [comentario, email])],
        llm=LLMConfig(
            default_provider="local",
            providers={"local": LLMProviderConfig(kind="ollama", model="m")},
        ),
    )
    ctx = ValidationContext(
        generators={
            "llm_post": FakeGenerator(),
            "email": FakeGenerator(depends_on_columns=["comentario"]),
        }
    )
    errors = validate_with_registry(schema, ctx)
    assert any("não determinística" in e.message for e in errors)


def test_depends_on_com_ciclo_gera_erro() -> None:
    a = _column("a", "tipo_a")
    b = _column("b", "tipo_b")
    schema = _schema([_table("t", [a, b])])
    ctx = ValidationContext(
        generators={
            "tipo_a": FakeGenerator(depends_on_columns=["b"]),
            "tipo_b": FakeGenerator(depends_on_columns=["a"]),
        }
    )
    errors = validate_with_registry(schema, ctx)
    assert any("ciclo" in e.message for e in errors)


def test_planner_validate_e_chamado_e_seus_erros_propagados() -> None:
    from dataipsum.errors import ValidationError

    schema = _schema([_table("t", [_column("id", "int")])])

    class PlannerWithError(FakePlanner):
        def validate(self, schema: object) -> list[object]:
            return [ValidationError(path="tables[0]", message="erro do planner")]

    ctx = ValidationContext(generators={"int": FakeGenerator()}, planner=PlannerWithError())
    errors = validate_with_registry(schema, ctx)
    assert any(e.message == "erro do planner" for e in errors)


# --- normalize_schema / implied_columns -------------------------------------


def test_normalize_schema_sem_ctx_devolve_o_mesmo_schema() -> None:
    schema = _schema([_table("t", [_column("id", "int")])])
    assert normalize_schema(schema) is schema


def test_normalize_schema_acrescenta_implied_columns_do_generator_ao_fim() -> None:
    comentario = _column("comentario", "llm_post", max_length=100)
    schema = _schema(
        [_table("t", [comentario])],
        llm=LLMConfig(
            default_provider="local",
            providers={"local": LLMProviderConfig(kind="ollama", model="m")},
        ),
    )
    implied = [_column("is_offensive", "boolean"), _column("is_placeholder", "boolean")]
    ctx = ValidationContext(generators={"llm_post": FakeGenerator(implied=implied)})
    normalized = normalize_schema(schema, ctx)
    names = [c.name for c in normalized.tables[0].columns]
    assert names == ["comentario", "is_offensive", "is_placeholder"]


def test_normalize_schema_acrescenta_implied_columns_do_planner() -> None:
    schema = _schema([_table("thread_tbl", [_column("id", "int")])])
    implied = [_column("seq", "int"), _column("autor", "ref")]
    ctx = ValidationContext(generators={"int": FakeGenerator()}, planner=FakePlanner(implied))
    normalized = normalize_schema(schema, ctx)
    names = [c.name for c in normalized.tables[0].columns]
    assert names == ["id", "seq", "autor"]


def test_normalize_schema_rejeita_colisao_com_coluna_declarada() -> None:
    is_offensive = _column("is_offensive", "boolean")
    comentario = _column("comentario", "llm_post", max_length=100)
    schema = _schema(
        [_table("t", [comentario, is_offensive])],
        llm=LLMConfig(
            default_provider="local",
            providers={"local": LLMProviderConfig(kind="ollama", model="m")},
        ),
    )
    implied = [_column("is_offensive", "boolean")]
    ctx = ValidationContext(generators={"llm_post": FakeGenerator(implied=implied)})
    with pytest.raises(SchemaError) as exc_info:
        normalize_schema(schema, ctx)
    assert "is_offensive" in str(exc_info.value)


def test_normalize_schema_dedup_por_nome_entre_generator_e_planner() -> None:
    comentario = _column("comentario", "llm_post", max_length=100)
    schema = _schema(
        [_table("t", [comentario])],
        llm=LLMConfig(
            default_provider="local",
            providers={"local": LLMProviderConfig(kind="ollama", model="m")},
        ),
    )
    generator_implied = [_column("is_offensive", "boolean")]
    planner_implied = [_column("is_offensive", "boolean"), _column("seq", "int")]
    ctx = ValidationContext(
        generators={"llm_post": FakeGenerator(implied=generator_implied)},
        planner=FakePlanner(planner_implied),
    )
    normalized = normalize_schema(schema, ctx)
    names = [c.name for c in normalized.tables[0].columns]
    assert names == ["comentario", "is_offensive", "seq"]
