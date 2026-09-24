"""JSON Schema exportável do modelo `Schema` (DD-00 §3.3).

A trilha H versiona o resultado de `export_json_schema()` e testa que ele não
diverge do modelo Pydantic (o próprio `.model_json_schema()` já garante isso,
porque é gerado a partir do modelo, nunca escrito à mão).
"""

from __future__ import annotations

from typing import Any

from dataipsum.schema.models import Schema


def export_json_schema() -> dict[str, Any]:
    """JSON Schema determinístico do `Schema`, com definições auxiliares embutidas."""
    return Schema.model_json_schema()
