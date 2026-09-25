"""Resolução de `ddl_for`/`avro_schema` (trilha F, DD-02 §0 e §E.3.3) em tempo de
execução.

A trilha E depende de duas funções que a trilha F entrega em paralelo, como sua
"sub-entrega prioritária" (DD-02 §0, F.4): `ddl_for(schema, dialect)` (DDL por
dialeto, usado por `create_tables`) e `avro_schema(schema, table)` (usado pelo sink
Kafka). Como as duas trilhas rodaram em worktrees separados, este módulo resolve a
implementação real por nome, em tempo de execução, via `dataipsum.schema_io` — nunca
por import estático (que quebraria caso o módulo ainda não exponha o símbolo).

As assinaturas aqui são exatamente as de F.4: por **schema inteiro**, não por
tabela, porque `ddl_for`/`avro_schema` precisam resolver colunas `ref` contra a
`TableSpec` referenciada (`find_table`), que só existe no `Schema` completo. Um
sink só recebe a própria `TableSpec` em `open()`; o `Schema` inteiro chega por
`RunContext.schema` (ver `contracts/sink.py`), passado pelo chamador (o worker,
DD-01). Os sites de chamada (`postgres_sink.py`, `mysql_sink.py`, `kafka_sink.py`)
levantam `SinkError` com mensagem clara quando `RunContext.schema` é `None`.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Protocol, cast

from dataipsum.errors import SinkError

if TYPE_CHECKING:
    from dataipsum.contracts.sink import RunContext
    from dataipsum.schema.models import Schema

SCHEMA_IO_MODULE = "dataipsum.schema_io"


class DdlFor(Protocol):
    def __call__(self, schema: Schema, dialect: str) -> str: ...


class AvroSchemaFor(Protocol):
    def __call__(self, schema: Schema, table: str) -> dict[str, object]: ...


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


def require_schema(run: RunContext) -> Schema:
    """`RunContext.schema`, ou `SinkError` com uma mensagem clara em vez de um erro
    de atributo/tipo obscuro quando o chamador não o forneceu."""
    if run.schema is None:
        raise SinkError(
            "esta operação exige o schema completo da execução (RunContext.schema), "
            "necessário para resolver colunas 'ref' contra a tabela referenciada "
            "(DD-02 F.4); o chamador (o worker, DD-01) precisa passá-lo."
        )
    return run.schema
