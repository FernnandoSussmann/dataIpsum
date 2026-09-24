"""Carrega e valida o schema YAML (DD-00 §3.3, §6.1).

`load_schema` cobre as camadas 1 (limites do documento) e 2 (estrutura, Pydantic) de
"Validação em camadas". As camadas 3 e 4 (nomes/tipos e validação delegada ao
registry) ficam em `validate`, que devolve um `ValidationReport` em vez de lançar,
porque dependem de um `ValidationContext` (registry) que pode não existir ainda.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError
from pydantic_core import ErrorDetails

from dataipsum.errors import SchemaError, ValidationError
from dataipsum.schema.models import (
    MAX_COLUMNS_PER_TABLE,
    MAX_TABLES,
    Schema,
    ValidationContext,
    validate_with_registry,
)

MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024
MAX_DEPTH = 20
MAX_PARAMS_BYTES = 64 * 1024

_FORBIDDEN_SECRET_FIELDS = frozenset({"api_key", "password", "token"})


@dataclass(frozen=True)
class ValidationReport:
    is_valid: bool
    errors: list[ValidationError]


class _NoAliasSafeLoader(yaml.SafeLoader):
    """`SafeLoader` que rejeita âncoras e aliases (proteção contra billion laughs).

    Tags customizadas já são rejeitadas pelo `SafeLoader` (só resolve as tags da
    especificação YAML), então não precisam de tratamento extra aqui.
    """

    def compose_node(self, parent: yaml.nodes.Node | None, index: int) -> yaml.nodes.Node | None:
        # `check_event` (totalmente tipado) força o parser a expor o próximo evento em
        # `self.current_event`. Um alias (`*nome`) É um `NodeEvent` com `anchor` preenchido
        # (o nome referenciado), e uma âncora (`&nome`) também aparece como `anchor` no
        # evento do nó que a declara; então checar esse atributo cobre os dois casos, sem
        # precisar chamar `get_event`/`peek_event` (não tipados em `yaml-stubs`).
        self.check_event()
        anchor = getattr(self.current_event, "anchor", None)
        if anchor is not None:
            raise yaml.YAMLError(
                f"âncoras/aliases não são permitidos no schema (âncora/alias '{anchor}')"
            )
        return super().compose_node(parent, index)


def _safe_yaml_load(text: str) -> object:
    try:
        # _NoAliasSafeLoader subclassa SafeLoader e só endurece a rejeição de
        # âncoras/aliases; exceção B506 registrada em security/exceptions.yaml.
        return yaml.load(text, Loader=_NoAliasSafeLoader)  # nosec B506
    except yaml.YAMLError as exc:
        raise SchemaError([ValidationError(path="$", message=f"YAML inválido: {exc}")]) from exc


def _read_source(source: Path | str | dict[str, object]) -> object:
    if isinstance(source, dict):
        return source
    text = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
    size = len(text.encode("utf-8"))
    if size > MAX_FILE_SIZE_BYTES:
        message = f"arquivo excede o limite de {MAX_FILE_SIZE_BYTES} bytes ({size} bytes)"
        raise SchemaError([ValidationError(path="$", message=message)])
    return _safe_yaml_load(text)


def _max_depth(node: object, current: int = 0) -> int:
    if isinstance(node, dict):
        return max((_max_depth(value, current + 1) for value in node.values()), default=current)
    if isinstance(node, list):
        return max((_max_depth(item, current + 1) for item in node), default=current)
    return current


def _build_path(prefix: str, key: str) -> str:
    return key if not prefix else f"{prefix}.{key}"


def _scan_forbidden_secrets(node: object, path: str = "") -> list[ValidationError]:
    if isinstance(node, dict):
        direct = [
            ValidationError(
                path=_build_path(path, str(key)),
                message=(
                    f"campo '{key}' não é permitido; use '{key}_env' para referenciar "
                    "o NOME de uma variável de ambiente com o segredo"
                ),
            )
            for key in node
            if key in _FORBIDDEN_SECRET_FIELDS
        ]
        nested = [
            error
            for key, value in node.items()
            if key not in _FORBIDDEN_SECRET_FIELDS
            for error in _scan_forbidden_secrets(value, _build_path(path, str(key)))
        ]
        return direct + nested
    if isinstance(node, list):
        return [
            error
            for index, item in enumerate(node)
            for error in _scan_forbidden_secrets(item, f"{path}[{index}]")
        ]
    return []


def _params_size_errors(
    table_index: int, column_index: int, params: object
) -> list[ValidationError]:
    if not isinstance(params, dict):
        return []
    size = len(json.dumps(params, ensure_ascii=False).encode("utf-8"))
    if size <= MAX_PARAMS_BYTES:
        return []
    message = f"'params' excede o limite de {MAX_PARAMS_BYTES} bytes serializado ({size} bytes)"
    return [
        ValidationError(
            path=f"tables[{table_index}].columns[{column_index}].params", message=message
        )
    ]


def _table_limit_errors(table_index: int, table: object) -> list[ValidationError]:
    if not isinstance(table, dict):
        return []
    columns = table.get("columns")
    if not isinstance(columns, list):
        return []
    errors = []
    if len(columns) > MAX_COLUMNS_PER_TABLE:
        errors.append(
            ValidationError(
                path=f"tables[{table_index}].columns",
                message=(
                    f"no máximo {MAX_COLUMNS_PER_TABLE} colunas por tabela, recebido {len(columns)}"
                ),
            )
        )
    errors.extend(
        error
        for column_index, column in enumerate(columns)
        if isinstance(column, dict)
        for error in _params_size_errors(table_index, column_index, column.get("params"))
    )
    return errors


def _document_limit_errors(parsed_document: object) -> list[ValidationError]:
    if not isinstance(parsed_document, dict):
        return [ValidationError(path="$", message="o documento precisa ser um mapeamento (objeto)")]
    errors: list[ValidationError] = []
    if _max_depth(parsed_document) > MAX_DEPTH:
        errors.append(
            ValidationError(
                path="$", message=f"profundidade do documento excede o limite de {MAX_DEPTH} níveis"
            )
        )
    tables = parsed_document.get("tables")
    if isinstance(tables, list):
        if len(tables) > MAX_TABLES:
            errors.append(
                ValidationError(
                    path="tables", message=f"no máximo {MAX_TABLES} tabelas, recebido {len(tables)}"
                )
            )
        errors.extend(
            error
            for table_index, table in enumerate(tables)
            for error in _table_limit_errors(table_index, table)
        )
    return errors


def _format_loc(loc: tuple[object, ...]) -> str:
    parts: list[str] = []
    for part in loc:
        if isinstance(part, int) and parts:
            parts[-1] = f"{parts[-1]}[{part}]"
        else:
            parts.append(str(part))
    return ".".join(parts) if parts else "$"


def _convert_pydantic_error(error: ErrorDetails) -> ValidationError:
    return ValidationError(path=_format_loc(tuple(error["loc"])), message=str(error["msg"]))


def load_schema(source: Path | str | dict[str, object]) -> Schema:
    """Carrega um schema de um caminho, de um texto YAML ou de um `dict` já parseado.

    Camada 1 (limites do documento) e camada 2 (estrutura, Pydantic), acumulando
    todos os erros de cada camada antes de lançar `SchemaError`.
    """
    parsed_document = _read_source(source)
    layer_1_errors = _document_limit_errors(parsed_document) + _scan_forbidden_secrets(
        parsed_document
    )
    if layer_1_errors:
        raise SchemaError(layer_1_errors)
    try:
        return Schema.model_validate(parsed_document)
    except PydanticValidationError as exc:
        raise SchemaError([_convert_pydantic_error(error) for error in exc.errors()]) from exc


def validate(schema: Schema, ctx: ValidationContext | None = None) -> ValidationReport:
    """Camadas 3 e 4 de "Validação em camadas": delegadas ao registry via `ctx`."""
    errors = validate_with_registry(schema, ctx)
    return ValidationReport(is_valid=not errors, errors=errors)
