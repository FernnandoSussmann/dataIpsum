"""Validação do JSON Schema publicado contra exemplos reais (DD-02 H.5).

Usa a lib `jsonschema` (dependência transitiva já presente no ambiente de
dev, ver `uv.lock`) quando disponível. Sem ela, os testes são pulados com
motivo, e a validação estrutural equivalente já é coberta por
`tests/core/unit/test_schema_jsonschema.py` (via `Schema.model_validate`,
DD-00 S2) — este módulo não adiciona nenhuma dependência nova.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from dataipsum.schema.jsonschema import export_json_schema

REPO_ROOT = Path(__file__).resolve().parents[3]
LOJA_YAML = REPO_ROOT / "examples" / "loja.yaml"


@pytest.fixture
def jsonschema_lib() -> Any:
    return pytest.importorskip("jsonschema")


def _validator(jsonschema_lib: Any, document: dict[str, object]) -> Any:
    validator_class = jsonschema_lib.validators.validator_for(document)
    validator_class.check_schema(document)
    return validator_class(document)


def test_json_schema_valida_examples_loja(jsonschema_lib: Any) -> None:
    document = export_json_schema()
    instance = yaml.safe_load(LOJA_YAML.read_text(encoding="utf-8"))
    _validator(jsonschema_lib, document).validate(instance)


def test_json_schema_rejeita_campo_desconhecido(jsonschema_lib: Any) -> None:
    document = export_json_schema()
    instance = yaml.safe_load(LOJA_YAML.read_text(encoding="utf-8"))
    instance["campo_nao_declarado"] = "valor"
    with pytest.raises(jsonschema_lib.ValidationError):
        _validator(jsonschema_lib, document).validate(instance)


def test_json_schema_rejeita_version_2(jsonschema_lib: Any) -> None:
    document = export_json_schema()
    instance = yaml.safe_load(LOJA_YAML.read_text(encoding="utf-8"))
    instance["version"] = 2
    with pytest.raises(jsonschema_lib.ValidationError):
        _validator(jsonschema_lib, document).validate(instance)


def test_json_schema_rejeita_tipos_errados(jsonschema_lib: Any) -> None:
    document = export_json_schema()
    instance = yaml.safe_load(LOJA_YAML.read_text(encoding="utf-8"))
    instance["chunk_size"] = "dez mil"
    with pytest.raises(jsonschema_lib.ValidationError):
        _validator(jsonschema_lib, document).validate(instance)


def test_json_schema_e_um_documento_json_valido() -> None:
    document = export_json_schema()
    assert json.loads(json.dumps(document)) == document
