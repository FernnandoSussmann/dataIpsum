"""JSON Schema exportável do modelo `Schema` (DD-00 §3.3).

A trilha H versiona o resultado de `export_json_schema()` em `schemas/dataipsum-schema.v1.json`
e testa que ele não diverge do modelo Pydantic (o próprio `.model_json_schema()` já garante
isso, porque é gerado a partir do modelo, nunca escrito à mão). O `$id` é um identificador
estável do contrato (DD-02, trilha H, H.3.1), não uma URL resolvível.
"""

from __future__ import annotations

from typing import Any

from dataipsum.schema.models import Schema

SCHEMA_ID = "https://dataipsum.local/schemas/dataipsum-schema.v1.json"


def export_json_schema() -> dict[str, Any]:
    """JSON Schema determinístico do `Schema`, com `$id` e definições auxiliares embutidas."""
    return {"$id": SCHEMA_ID, **Schema.model_json_schema()}
