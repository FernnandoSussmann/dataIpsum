"""Regras de compatibilidade do contrato (DD-02 H.3.2, H.5).

Neste marco (version: 1 é o único aceito), a garantia testável é: um schema
mínimo (só os campos obrigatórios) continua válido, e acrescentar um campo
opcional novo ao modelo não quebra a validação dos exemplos existentes do
repositório (o que caracteriza uma "mudança aditiva", H.3.2).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dataipsum import load_schema, validate
from dataipsum.schema.models import Schema

REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCHEMA = REPO_ROOT / "examples" / "contrato" / "minimo.yaml"
LOJA_SCHEMA = REPO_ROOT / "examples" / "loja.yaml"


def test_schema_minimo_v1_e_valido() -> None:
    schema = load_schema(MINIMAL_SCHEMA)
    report = validate(schema)
    assert report.is_valid, report.errors


def test_apenas_version_1_e_aceita() -> None:
    document = yaml.safe_load(MINIMAL_SCHEMA.read_text(encoding="utf-8"))
    document["version"] = 2
    with pytest.raises(Exception, match="version"):  # noqa: B017 -- qualquer erro pydantic
        Schema.model_validate(document)


def test_campos_conhecidos_do_exemplo_completo_continuam_validos() -> None:
    """`examples/loja.yaml` usa só campos documentados em DD-00 §3.3; ele
    precisa continuar válido enquanto o contrato for aditivo em `version: 1`."""
    schema = load_schema(LOJA_SCHEMA)
    report = validate(schema)
    assert report.is_valid, report.errors


def test_campos_desconhecidos_de_topo_sao_rejeitados_por_extra_forbid() -> None:
    """`model_config = ConfigDict(extra="forbid")` é a base para a UI poder
    detectar uma mudança incompatível: um campo removido do modelo passaria a
    ser "desconhecido" e falharia aqui, em vez de ser silenciosamente
    ignorado."""
    document = yaml.safe_load(MINIMAL_SCHEMA.read_text(encoding="utf-8"))
    document["campo_que_nao_existe_no_contrato"] = True
    with pytest.raises(Exception, match="campo_que_nao_existe_no_contrato"):  # noqa: B017
        Schema.model_validate(document)
