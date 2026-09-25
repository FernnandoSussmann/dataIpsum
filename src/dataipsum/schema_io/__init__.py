"""Trilha F (DD-02): import/export de schema (DDL SQL, Avro Schema).

Expõe as APIs de F.4: `ddl_for`/`avro_schema` (sub-entregas prioritárias, consumidas
pela trilha E), `export_schema` (implementação de `dataipsum.api.export_schema`) e
`import_ddl` (implementação de `dataipsum.api.import_ddl`, M3).
"""

from __future__ import annotations

from dataipsum.registry import Registry
from dataipsum.schema_io.avro_export import avro_schema
from dataipsum.schema_io.ddl_export import ddl_for
from dataipsum.schema_io.ddl_import import ImportReport, import_ddl
from dataipsum.schema_io.export import SchemaFormat, export_schema

__all__ = [
    "ImportReport",
    "SchemaFormat",
    "avro_schema",
    "ddl_for",
    "export_schema",
    "import_ddl",
    "register",
]


def register(registry: Registry) -> None:
    """Vazio: a trilha F não registra geradores/sinks (DD-02 §0)."""
