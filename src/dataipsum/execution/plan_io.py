"""Reconstrução do `RunPlan` a partir do `manifest.plan` (DD-01 §D.3.5, `resume`).

`RunPlan.to_json_dict` já existe no contrato (DD-00); a direção inversa é só
consumida por `resume` (o `generate` nunca precisa desserializar um plano), então
ela mora na trilha D, não no contrato.
"""

from __future__ import annotations

from typing import Any, cast

from dataipsum.contracts.planner import ChunkSpec, ParentRef, RunPlan, TablePlan


def _parent_ref_from_json(data: dict[str, Any] | None) -> ParentRef | None:
    if data is None:
        return None
    return ParentRef(
        table=data["table"],
        first_index=data["first_index"],
        count=data["count"],
        first_child_offset=data["first_child_offset"],
    )


def _chunk_spec_from_json(data: dict[str, Any]) -> ChunkSpec:
    return ChunkSpec(
        id=data["id"],
        first_row=data["first_row"],
        rows=data["rows"],
        parent=_parent_ref_from_json(cast(dict[str, Any] | None, data.get("parent"))),
    )


def run_plan_from_json_dict(data: dict[str, Any]) -> RunPlan:
    return RunPlan(
        order=tuple(data["order"]),
        tables={
            name: TablePlan(
                rows=table["rows"],
                chunks=tuple(_chunk_spec_from_json(chunk) for chunk in table["chunks"]),
            )
            for name, table in data["tables"].items()
        },
    )
