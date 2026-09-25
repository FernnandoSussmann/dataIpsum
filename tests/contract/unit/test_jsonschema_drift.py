"""Teste de drift do JSON Schema publicado (DD-02, trilha H, H.3.1/H.5).

`schemas/dataipsum-schema.v1.json` é gerado uma única vez a partir de
`dataipsum.schema.jsonschema.export_json_schema()` e versionado no git. Este
teste regenera o JSON Schema e compara byte a byte com o arquivo versionado:
qualquer diferença indica que o modelo Pydantic mudou sem que o contrato
tenha sido atualizado (e justificado pelas regras de compatibilidade de
`docs/api/README.md`, DD-02 H.3.2).
"""

from __future__ import annotations

import json
from pathlib import Path

from dataipsum.schema.jsonschema import SCHEMA_ID, export_json_schema

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONED_SCHEMA_PATH = REPO_ROOT / "schemas" / "dataipsum-schema.v1.json"


def _canonical_bytes(document: dict[str, object]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def test_arquivo_versionado_existe() -> None:
    assert VERSIONED_SCHEMA_PATH.is_file(), (
        f"'{VERSIONED_SCHEMA_PATH}' não existe; gere com "
        "`export_json_schema()` e versione no git (DD-02 H.3.1)"
    )


def test_json_schema_gerado_e_identico_ao_versionado() -> None:
    generated = _canonical_bytes(export_json_schema())
    on_disk = VERSIONED_SCHEMA_PATH.read_bytes()
    assert generated == on_disk, (
        "'schemas/dataipsum-schema.v1.json' diverge do modelo Pydantic atual. "
        "Regenere o arquivo e justifique a mudança pelas regras de "
        "compatibilidade em docs/api/README.md (DD-02 H.3.2)."
    )


def test_json_schema_versionado_tem_id_estavel() -> None:
    on_disk = json.loads(VERSIONED_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert on_disk["$id"] == SCHEMA_ID
    assert on_disk["$id"] == "https://dataipsum.local/schemas/dataipsum-schema.v1.json"
