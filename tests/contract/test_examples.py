"""Valida todo `examples/**/*.yaml` do repositório (DD-02, trilha H, H.3.4).

Cada arquivo passa pelas duas camadas do contrato:
  1. `dataipsum.validate` (via `load_schema`), a fonte da verdade;
  2. o JSON Schema publicado em `schemas/dataipsum-schema.v1.json`, quando a
     lib `jsonschema` está disponível (ver `tests/contract/unit/test_jsonschema_validation.py`
     para o porquê de não ser uma dependência nova).

Exemplos que dependem de um provedor LLM não instalado como extra (ex.:
`kind: anthropic` sem o pacote `anthropic`) ou de um sink de banco/Kafka não
instalado (`postgres`, `mysql`, `kafka`) são pulados com o motivo, em vez de
falhar (DD-00 §3.2, DD-02 H.3.4). Para os demais, a tentativa de "rodar" via
`dataipsum.api.generate` fica registrada como skip explícito enquanto o
motor de execução (DD-01, trilha D) não existe neste worktree: validar a
estrutura já cobre o critério H-02, e o S5 de integração roda os exemplos de
ponta a ponta com o motor real (com fakes nos testes unitários da trilha D).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from dataipsum import load_schema, validate
from dataipsum.errors import SchemaError

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples"

_EXTRA_BY_LLM_PROVIDER_KIND = {"anthropic": "anthropic"}
_EXTRA_BY_PATH_COMPONENT = {"postgres": "psycopg", "mysql": "pymysql", "kafka": "confluent_kafka"}


def _example_yaml_files() -> list[Path]:
    # Só `*.yaml`: `examples/**` também tem `docker-compose.yml` (trilhas E/G), que
    # não são schemas dataIpsum (H.3.4 fala especificamente de `examples/**/*.yaml`).
    return sorted(EXAMPLES_DIR.rglob("*.yaml"))


def _required_extras(document: object, path: Path) -> set[str]:
    from_path = {
        module for component, module in _EXTRA_BY_PATH_COMPONENT.items() if component in path.parts
    }
    llm = document.get("llm") if isinstance(document, dict) else None
    providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
    from_llm = {
        _EXTRA_BY_LLM_PROVIDER_KIND[provider["kind"]]
        for provider in providers.values()
        if isinstance(provider, dict) and provider.get("kind") in _EXTRA_BY_LLM_PROVIDER_KIND
    }
    return from_path | from_llm


def _missing_extras(required_modules: set[str]) -> set[str]:
    return {module for module in required_modules if importlib.util.find_spec(module) is None}


@pytest.mark.parametrize("path", _example_yaml_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_exemplo_valida_pelo_loader_e_pelo_json_schema(path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))

    schema = load_schema(path)
    report = validate(schema)
    assert report.is_valid, f"{path}: {report.errors}"

    jsonschema_lib = pytest.importorskip("jsonschema")
    from dataipsum.schema.jsonschema import export_json_schema

    json_schema = export_json_schema()
    validator_class = jsonschema_lib.validators.validator_for(json_schema)
    validator_class(json_schema).validate(document)


@pytest.mark.parametrize("path", _example_yaml_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_exemplo_roda_com_fakes_quando_extras_disponiveis(path: Path, tmp_path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = _missing_extras(_required_extras(document, path))
    if missing:
        pytest.skip(f"{path}: extra(s) ausente(s) para rodar: {sorted(missing)}")

    schema = load_schema(path)
    from dataipsum.api import RunResult, generate
    from dataipsum.config import RunOptions, SinkConfig

    options = RunOptions(out_dir=tmp_path / "saida", sink=SinkConfig("csv"))
    try:
        result = generate(schema, options)
    except NotImplementedError as exc:
        pytest.skip(f"{path}: motor de execução ainda não implementado ({exc})")
    except SchemaError as exc:
        raise AssertionError(
            f"{path}: schema válido não deveria falhar em generate: {exc}"
        ) from exc
    else:
        assert isinstance(result, RunResult)


def test_pelo_menos_um_exemplo_foi_encontrado() -> None:
    assert _example_yaml_files(), "nenhum 'examples/**/*.yaml' foi encontrado"
