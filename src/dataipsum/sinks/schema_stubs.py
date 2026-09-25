"""Assinaturas stub de `ddl_for`/`avro_schema` (trilha F, DD-02 §0 e §E.3.3).

A trilha E depende de duas funções que a trilha F entrega em paralelo, como sua
"sub-entrega prioritária" (DD-02 §0, F.4): `ddl_for` (DDL por dialeto, usado por
`create_tables`) e `avro_schema` (usado pelo sink Kafka). Como as duas trilhas rodam
em worktrees separados, este módulo define **localmente** o formato esperado dessas
funções (`Protocol`) e resolve a implementação real por nome, em tempo de execução,
via `dataipsum.schema_io` — nunca por import estático (que quebraria caso o módulo
ainda não exponha o símbolo neste worktree). Quando a trilha F entregar `ddl_for`/
`avro_schema` em `dataipsum.schema_io`, a resolução passa a encontrá-las sem
nenhuma mudança neste arquivo (o encaixe do S5, DD-02 §0).

Nota de integração: `ddl_for` aqui é definido por tabela (`ddl_for(table, dialect)`),
porque o sink escreve uma tabela por vez (`Sink.open` recebe um `TableSpec`, não o
`Schema` inteiro). O F.4 do DD-02 descreve `ddl_for(schema, dialect)` no nível do
schema inteiro (para ordenar `CREATE TABLE`s por FK); reconciliar as duas
assinaturas é trabalho do S5. Enquanto isso, `create_tables` aqui gera só
`CREATE TABLE IF NOT EXISTS` da própria tabela, o que é suficiente para os
ambientes de teste a que a opção se destina (E.3.2).
"""

from __future__ import annotations

import importlib
from typing import Protocol, cast

from dataipsum.errors import SinkError
from dataipsum.schema.models import TableSpec

SCHEMA_IO_MODULE = "dataipsum.schema_io"


class DdlFor(Protocol):
    def __call__(self, table: TableSpec, dialect: str) -> str: ...


class AvroSchemaFor(Protocol):
    def __call__(self, table: TableSpec) -> dict[str, object]: ...


def _resolve(name: str) -> object:
    try:
        module = importlib.import_module(SCHEMA_IO_MODULE)
    except ImportError as exc:
        raise SinkError(
            f"'{name}' não está disponível: {SCHEMA_IO_MODULE} não pôde ser importado ({exc})"
        ) from exc
    candidate = getattr(module, name, None)
    if candidate is None:
        raise SinkError(
            f"'{name}' ainda não é exposto por {SCHEMA_IO_MODULE} (trilha F, DD-02). "
            "O encaixe acontece no step de integração S5."
        )
    return candidate


def load_ddl_for() -> DdlFor:
    return cast(DdlFor, _resolve("ddl_for"))


def load_avro_schema_for() -> AvroSchemaFor:
    return cast(AvroSchemaFor, _resolve("avro_schema"))
