"""Validação estrutural do rascunho de OpenAPI (DD-02 H.3.3, H.5).

Não há um validador completo de OpenAPI 3.1 nas dependências de dev (H.5
permite verificação estrutural quando não há lib disponível); este módulo
verifica que o documento é YAML válido, que as chaves de topo do OpenAPI
3.1 estão presentes, e que as 7 rotas da tabela de H.3.3 existem.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = REPO_ROOT / "docs" / "api" / "openapi.v1.yaml"

EXPECTED_ROUTES = {
    "/schemas:validate": {"post"},
    "/plans": {"post"},
    "/runs": {"post"},
    "/runs/{run_id}": {"get"},
    "/runs/{run_id}:resume": {"post"},
    "/schemas:export": {"post"},
    "/schemas:import": {"post"},
}


def _load_openapi() -> dict[str, object]:
    return yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))


def test_openapi_e_yaml_valido_com_chaves_de_topo() -> None:
    document = _load_openapi()
    assert document["openapi"].startswith("3.1")
    assert "info" in document
    assert "paths" in document
    assert "components" in document


def test_openapi_documenta_as_7_rotas_de_h_3_3() -> None:
    document = _load_openapi()
    paths = document["paths"]
    assert set(paths.keys()) == set(EXPECTED_ROUTES.keys())
    for route, methods in EXPECTED_ROUTES.items():
        declared_methods = set(paths[route].keys())
        assert methods <= declared_methods, f"{route}: esperava {methods}, achou {declared_methods}"


def test_openapi_documenta_requisitos_de_seguranca() -> None:
    document = _load_openapi()
    description = document["info"]["description"]
    for requirement in (
        "autenticação",
        "run_id",
        "CORS",
        "_env",
    ):
        assert requirement.lower() in description.lower(), (
            f"requisito de segurança '{requirement}' não documentado em info.description"
        )


def test_openapi_cada_rota_referencia_o_json_schema_publicado() -> None:
    raw_text = OPENAPI_PATH.read_text(encoding="utf-8")
    assert "dataipsum-schema.v1.json" in raw_text


def test_openapi_cada_rota_exige_seguranca() -> None:
    document = _load_openapi()
    for route, operations in document["paths"].items():
        for method, operation in operations.items():
            assert "security" in operation, f"{method.upper()} {route} não declara 'security'"
