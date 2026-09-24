"""Testes de `RunPlan` (DD-00 §3.5)."""

from __future__ import annotations

from dataipsum.contracts.planner import ChunkSpec, ParentRef, RunPlan, TablePlan


def test_run_plan_to_json_dict_e_serializavel() -> None:
    plan = RunPlan(
        order=("usuarios", "pedidos"),
        tables={
            "usuarios": TablePlan(rows=10, chunks=(ChunkSpec(id=1, first_row=0, rows=10),)),
            "pedidos": TablePlan(
                rows=20,
                chunks=(
                    ChunkSpec(
                        id=1,
                        first_row=0,
                        rows=20,
                        parent=ParentRef(
                            table="usuarios", first_index=0, count=10, first_child_offset=0
                        ),
                    ),
                ),
            ),
        },
    )
    as_dict = plan.to_json_dict()
    assert as_dict["order"] == ["usuarios", "pedidos"]
    assert as_dict["tables"]["pedidos"]["chunks"][0]["parent"]["table"] == "usuarios"
    assert as_dict["tables"]["usuarios"]["chunks"][0]["parent"] is None
