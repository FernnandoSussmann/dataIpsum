"""Flags inline (`--col`) convertidas em um `Schema` de tabela única (DD-00 §3.3).

O parsing das flags da CLI é da trilha G; `build_inline_schema` recebe as strings já
tokenizadas (uma por `--col`) e monta o `Schema`. A gramática de cada string é
`nome:tipo[:pk][:chave=valor...]`.

Os campos de primeira classe de `ColumnSpec` (`max_length`, `null_ratio`,
`invalid_ratio`, `format`, `locale`) são reconhecidos e atribuídos com o tipo certo
quando aparecem como `chave=valor`; qualquer outra chave vai para `params`, como
string, porque o parser de flags não tem acesso ao registry para saber o tipo
esperado por cada gerador (isso é validado na camada 4, em `validate_with_registry`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from dataipsum.errors import SchemaError, ValidationError
from dataipsum.schema.models import ColumnSpec, PrimaryKeySpec, Schema, TableSpec

_KNOWN_FIELD_PARSERS: dict[str, Callable[[str], object]] = {
    "max_length": int,
    "null_ratio": float,
    "invalid_ratio": float,
    "format": str,
    "locale": str,
}

_DEFAULT_PK_STRATEGY = "sequence"


@dataclass(frozen=True)
class _ParsedColumn:
    column: ColumnSpec
    is_pk: bool


def _parse_column(raw: str) -> _ParsedColumn:
    parts = raw.split(":")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"formato inválido em '{raw}': esperado 'nome:tipo[:pk][:chave=valor...]'")
    name, type_name, *flags = parts
    is_pk = "pk" in flags
    key_value_flags = [flag for flag in flags if flag != "pk"]
    invalid_flags = [flag for flag in key_value_flags if "=" not in flag]
    if invalid_flags:
        raise ValueError(
            f"flag inválida {invalid_flags[0]!r} em '{raw}': use 'pk' ou 'chave=valor'"
        )
    pairs = [flag.partition("=")[0::2] for flag in key_value_flags]
    empty_keys = [key for key, _ in pairs if not key]
    if empty_keys:
        raise ValueError(f"chave de parâmetro vazia em '{raw}'")
    known = {
        key: _KNOWN_FIELD_PARSERS[key](value) for key, value in pairs if key in _KNOWN_FIELD_PARSERS
    }
    params = {key: value for key, value in pairs if key not in _KNOWN_FIELD_PARSERS}
    column = ColumnSpec(name=name, type=type_name, params=params, **known)
    return _ParsedColumn(column=column, is_pk=is_pk)


def build_inline_schema(table: str, rows: int, cols: list[str]) -> Schema:
    """Constrói um `Schema` de uma única tabela a partir de flags `--col` já tokenizadas."""
    if not cols:
        raise SchemaError(
            [ValidationError(path="cols", message="é preciso informar ao menos uma coluna (--col)")]
        )
    errors: list[ValidationError] = []
    parsed: list[_ParsedColumn] = []
    for index, raw in enumerate(cols):
        try:
            parsed.append(_parse_column(raw))
        except ValueError as exc:
            errors.append(ValidationError(path=f"cols[{index}]", message=str(exc)))
    pk_names = [item.column.name for item in parsed if item.is_pk]
    if len(pk_names) > 1:
        errors.append(
            ValidationError(
                path="cols", message=f"mais de uma coluna marcada como 'pk': {pk_names}"
            )
        )
    if errors:
        raise SchemaError(errors)
    pk_name = pk_names[0] if pk_names else parsed[0].column.name
    table_spec = TableSpec(
        name=table,
        rows=rows,
        primary_key=PrimaryKeySpec(columns=[pk_name], strategy=_DEFAULT_PK_STRATEGY),
        columns=[item.column for item in parsed],
    )
    return Schema(version=1, tables=[table_spec])
