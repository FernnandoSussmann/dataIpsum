"""Round-trip schema -> DDL -> import -> schema equivalente (DD-02 §F.6)."""

from __future__ import annotations

import pytest

from dataipsum.schema.models import Schema
from dataipsum.schema_io import ddl_for, import_ddl


@pytest.mark.parametrize("dialect", ["postgres", "mysql"])
def test_round_trip_preserva_tipos_pk_e_fk(loja_schema: Schema, dialect: str) -> None:
    sql = ddl_for(loja_schema, dialect)
    imported_schema, _ = import_ddl(sql, dialect)

    original_by_name = {table.name: table for table in loja_schema.tables}
    imported_by_name = {table.name: table for table in imported_schema.tables}
    assert set(original_by_name) == set(imported_by_name)

    for name, original_table in original_by_name.items():
        imported_table = imported_by_name[name]
        assert imported_table.primary_key.columns == original_table.primary_key.columns
        original_column_names = {c.name for c in original_table.columns}
        imported_column_names = {c.name for c in imported_table.columns}
        assert original_column_names == imported_column_names

    usuarios_pedidos_ref = next(
        c for c in imported_by_name["pedidos"].columns if c.name == "usuario_id"
    )
    assert usuarios_pedidos_ref.type == "ref"
    assert usuarios_pedidos_ref.params["table"] == "usuarios"
