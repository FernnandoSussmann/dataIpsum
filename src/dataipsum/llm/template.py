"""Parser restrito de templates de prompt LLM (DD-01 §C.3.2).

Reconhece só `{identificador}` e `{identificador.identificador}`, com `{{`/`}}` como chaves
literais. Não usa `str.format`, `eval` nem Jinja: o corpo de cada variável é validado por regex
e resolvido por *lookup* em dicionários já calculados pelo chamador, nunca por acesso a atributo
ou execução de código.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dataipsum.errors import DataIpsumError, SchemaError, ValidationError

if TYPE_CHECKING:
    from dataipsum.schema.models import ColumnSpec, Schema, TableSpec

_IDENT_PATTERN = r"[a-z_][a-z0-9_]*"
_IDENT_RE = re.compile(_IDENT_PATTERN)
_MARKER_RE = re.compile(r"\{(" + _IDENT_PATTERN + r"(?:\." + _IDENT_PATTERN + r")?)\}")

MAX_VALUE_CHARS = 500
MAX_PROMPT_BYTES = 16 * 1024

_SENTINEL_OPEN = "\x00__DATAIPSUM_OPEN__\x00"
_SENTINEL_CLOSE = "\x00__DATAIPSUM_CLOSE__\x00"


class TemplateSyntaxError(DataIpsumError):
    pass


@dataclass(frozen=True)
class Var:
    """Referência a `{coluna}` (`len(path) == 1`) ou `{ref.coluna}` (`len(path) == 2`)."""

    path: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.path) not in (1, 2):
            raise ValueError("Var.path deve ter 1 ou 2 segmentos")

    def __str__(self) -> str:
        return "{" + ".".join(self.path) + "}"


Token = str | Var


def _parse_var_body(body: str) -> Var:
    segments = tuple(body.split("."))
    if len(segments) not in (1, 2) or not all(_IDENT_RE.fullmatch(s) for s in segments):
        raise TemplateSyntaxError(f"variável inválida: '{{{body}}}' (só 1 nível de '.')")
    return Var(segments)


def parse_template(text: str) -> tuple[Token, ...]:
    """Tokeniza `text` em literais e `Var`. Levanta `TemplateSyntaxError` em chaves malformadas."""
    tokens: list[Token] = []
    literal: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "{":
            if index + 1 < length and text[index + 1] == "{":
                literal.append("{")
                index += 2
                continue
            end = text.find("}", index + 1)
            if end == -1:
                raise TemplateSyntaxError(f"chave '{{' sem fechamento (posição {index})")
            var = _parse_var_body(text[index + 1 : end])
            if literal:
                tokens.append("".join(literal))
                literal = []
            tokens.append(var)
            index = end + 1
            continue
        if char == "}":
            if index + 1 < length and text[index + 1] == "}":
                literal.append("}")
                index += 2
                continue
            raise TemplateSyntaxError(f"chave '}}' sem abertura (posição {index})")
        literal.append(char)
        index += 1
    if literal:
        tokens.append("".join(literal))
    return tuple(tokens)


def extract_markers(text: str) -> tuple[Var, ...]:
    """Varredura tolerante (usada na validação de textos de pool, §C.3.4).

    Só marcadores bem formados (`{col}`/`{ref.col}`) são reconhecidos; qualquer outra chave
    (inclusive `{{`/`}}`) é tratada como texto literal, sem erro.
    """
    sanitized = text.replace("{{", _SENTINEL_OPEN).replace("}}", _SENTINEL_CLOSE)
    return tuple(Var(tuple(match.group(1).split("."))) for match in _MARKER_RE.finditer(sanitized))


def unknown_markers(text: str, valid_vars: Iterable[Var]) -> tuple[Var, ...]:
    """Marcadores de `text` que não estão em `valid_vars` (§C.3.4, "marcador desconhecido")."""
    known = frozenset(valid_vars)
    return tuple(var for var in extract_markers(text) if var not in known)


def _stringify(value: object) -> str:
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return normalized[:MAX_VALUE_CHARS]


def render(
    tokens: Iterable[Token],
    *,
    same_row: Mapping[str, object],
    parent_values: Mapping[str, Mapping[str, object]],
) -> str:
    """Substitui cada `Var` pelo valor já resolvido, trunca por valor e pelo total (§C.3.2)."""
    parts = [
        token
        if isinstance(token, str)
        else _stringify(
            same_row[token.path[0]]
            if len(token.path) == 1
            else parent_values[token.path[0]][token.path[1]]
        )
        for token in tokens
    ]
    rendered = "".join(parts)
    encoded = rendered.encode("utf-8")
    if len(encoded) <= MAX_PROMPT_BYTES:
        return rendered
    return encoded[:MAX_PROMPT_BYTES].decode("utf-8", errors="ignore")


def fill_pool_text(
    text: str,
    *,
    same_row: Mapping[str, object],
    parent_values: Mapping[str, Mapping[str, object]],
) -> str:
    """Preenche os marcadores literais de um texto de pool (§C.3.4, "Por linha").

    Marcadores não resolvíveis (fora do escopo de `same_row`/`parent_values`) são deixados
    como estão; a chamada é feita só depois da validação (`unknown_markers`), então isso não
    deveria acontecer em uso normal.
    """

    def _replace(match: re.Match[str]) -> str:
        segments = tuple(match.group(1).split("."))
        if len(segments) == 1:
            if segments[0] not in same_row:
                return match.group(0)
            return _stringify(same_row[segments[0]])
        ref_name, sub_name = segments
        parent = parent_values.get(ref_name)
        if parent is None or sub_name not in parent:
            return match.group(0)
        return _stringify(parent[sub_name])

    sanitized = text.replace("{{", _SENTINEL_OPEN).replace("}}", _SENTINEL_CLOSE)
    filled = _MARKER_RE.sub(_replace, sanitized)
    return filled.replace(_SENTINEL_OPEN, "{").replace(_SENTINEL_CLOSE, "}")


def _find_column(columns: Iterable[ColumnSpec], name: str) -> ColumnSpec | None:
    return next((column for column in columns if column.name == name), None)


def _find_table(schema: Schema, name: str) -> TableSpec | None:
    return next((table for table in schema.tables if table.name == name), None)


class TemplateValidator:
    """Valida um template LLM contra o schema (DD-01 §C.3.2, `TemplateValidator`)."""

    def validate(
        self, schema: Schema, table: TableSpec, column: ColumnSpec, template_text: str
    ) -> tuple[Var, ...]:
        try:
            tokens = parse_template(template_text)
        except TemplateSyntaxError as exc:
            raise SchemaError(
                [ValidationError(path=f"{table.name}.{column.name}", message=str(exc))]
            ) from exc
        variables = tuple(token for token in tokens if isinstance(token, Var))
        errors = [
            error
            for var in variables
            for error in (self._validate_var(schema, table, column, var),)
            if error is not None
        ]
        if errors:
            raise SchemaError(errors)
        return variables

    def _validate_var(
        self, schema: Schema, table: TableSpec, column: ColumnSpec, var: Var
    ) -> ValidationError | None:
        prefix = f"{table.name}.{column.name}.prompt"
        label = str(var)
        if len(var.path) == 1:
            return self._validate_same_row(table, prefix, label, var.path[0])
        return self._validate_parent(schema, table, prefix, label, var.path[0], var.path[1])

    def _validate_same_row(
        self, table: TableSpec, prefix: str, label: str, name: str
    ) -> ValidationError | None:
        if name in table.primary_key.columns:
            return ValidationError(
                path=prefix,
                message=(
                    f"'{label}' referencia a chave primária; o valor de chaves nunca entra "
                    "no prompt"
                ),
            )
        target = _find_column(table.columns, name)
        if target is None:
            return ValidationError(
                path=prefix, message=f"'{label}' referencia coluna inexistente '{name}'"
            )
        if target.type == "ref":
            return ValidationError(
                path=prefix,
                message=(
                    f"'{label}' referencia uma coluna de referência; use "
                    f"'{{{name}.coluna}}' para navegar até o pai, nunca o valor da chave"
                ),
            )
        if target.is_llm:
            return ValidationError(
                path=prefix,
                message=(
                    f"'{label}' referencia outra coluna LLM da mesma linha, o que não é permitido"
                ),
            )
        return None

    def _validate_parent(
        self,
        schema: Schema,
        table: TableSpec,
        prefix: str,
        label: str,
        ref_name: str,
        sub_name: str,
    ) -> ValidationError | None:
        ref_column = _find_column(table.columns, ref_name)
        if ref_column is None or ref_column.type != "ref":
            return ValidationError(
                path=prefix,
                message=(
                    f"'{label}' começa em '{ref_name}', que não é uma coluna de referência "
                    "('ref') desta tabela"
                ),
            )
        target_table_name = ref_column.params.get("table")
        parent_table = _find_table(schema, str(target_table_name)) if target_table_name else None
        if parent_table is None:
            return ValidationError(
                path=prefix,
                message=(
                    f"'{label}': coluna de referência '{ref_name}' não aponta para uma tabela "
                    "válida"
                ),
            )
        if sub_name in parent_table.primary_key.columns:
            return ValidationError(
                path=prefix,
                message=(
                    f"'{label}' referencia a chave primária do pai; o valor de chaves nunca "
                    "entra no prompt"
                ),
            )
        parent_column = _find_column(parent_table.columns, sub_name)
        if parent_column is None:
            return ValidationError(
                path=prefix,
                message=(
                    f"'{label}' referencia coluna inexistente '{sub_name}' em '{parent_table.name}'"
                ),
            )
        if parent_column.type == "ref":
            return ValidationError(
                path=prefix,
                message=(
                    f"'{label}' referencia outra chave estrangeira do pai; o valor de chaves "
                    "nunca entra no prompt"
                ),
            )
        if parent_column.is_llm:
            return ValidationError(
                path=prefix,
                message=(
                    f"'{label}' referencia coluna LLM '{sub_name}' do pai; só colunas "
                    "determinísticas do pai podem ser referenciadas"
                ),
            )
        return None
