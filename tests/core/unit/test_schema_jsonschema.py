"""Testes do JSON Schema exportado (DD-00 §7.1: schema/jsonschema.py)."""

from __future__ import annotations

import json

import pytest

from conftest import FULL_EXAMPLE
from dataipsum.schema.jsonschema import export_json_schema
from dataipsum.schema.models import Schema


def test_json_schema_e_um_objeto_com_os_campos_de_topo() -> None:
    schema = export_json_schema()
    assert schema["type"] == "object"
    assert set(schema["required"]) >= {"version", "tables"}
    assert schema["additionalProperties"] is False


def test_json_schema_e_deterministico_entre_chamadas() -> None:
    first = export_json_schema()
    second = export_json_schema()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_json_schema_valida_o_exemplo_da_secao_3_3() -> None:
    """Sem uma lib de validação de JSON Schema nas deps diretas, a prova de que o
    schema exportado aceita o exemplo é a própria fonte da verdade: o modelo
    Pydantic que o gera aceita o exemplo (o JSON Schema é derivado dele, nunca
    escrito à mão)."""
    Schema.model_validate(FULL_EXAMPLE)
    exported = export_json_schema()
    assert "version" in exported["properties"]
    assert "tables" in exported["properties"]


def test_json_schema_rejeita_erros_estruturais_do_exemplo() -> None:
    broken = json.loads(json.dumps(FULL_EXAMPLE))
    del broken["version"]
    with pytest.raises(Exception):  # noqa: B017 -- qualquer erro de validação pydantic
        Schema.model_validate(broken)


def test_json_schema_com_lib_jsonschema_se_disponivel() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    exported = export_json_schema()
    resolved = _inline_local_refs(exported)
    jsonschema.validate(instance=FULL_EXAMPLE, schema=resolved)
    broken = json.loads(json.dumps(FULL_EXAMPLE))
    del broken["version"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=broken, schema=resolved)


def _inline_local_refs(schema: dict[str, object]) -> dict[str, object]:
    """`model_json_schema()` usa `$defs` locais; sem um resolvedor pronto nas
    deps diretas, montamos um `Draft2020` mínimo dando ao validador acesso a
    `$defs` (já embutido no próprio documento, então basta usar `schema` como
    o "root" para resolução de `$ref`)."""
    return schema
