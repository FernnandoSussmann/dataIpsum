"""Smoke tests de importabilidade e das dataclasses dos contratos (DD-00 §3.5)."""

from __future__ import annotations

import numpy as np

from dataipsum.contracts.executor import BlockedBy, ChunkResult, ChunkResultFlags, ChunkTask
from dataipsum.contracts.generator import RowBatch
from dataipsum.contracts.llm import LLMRequest, LLMResponse
from dataipsum.contracts.planner import ChunkSpec
from dataipsum.contracts.sink import RunContext, SinkCapabilities, SinkReceipt


def test_row_batch_guarda_indices_e_mascara() -> None:
    batch = RowBatch(rows=np.array([0, 1, 2], dtype=np.int64))
    assert batch.invalid_mask is None
    assert batch.rows.tolist() == [0, 1, 2]


def test_chunk_task_e_autocontido() -> None:
    task = ChunkTask(
        table="usuarios",
        chunk_spec=ChunkSpec(id=1, first_row=0, rows=10),
        schema={"version": 1},
        root_seed=42,
        sink_options={},
        run_options={},
    )
    assert task.chunk_spec.rows == 10


def test_chunk_result_com_flags_e_blocked_by() -> None:
    result = ChunkResult(
        table="pedidos",
        chunk_id=1,
        status="pending",
        rows=0,
        flags=ChunkResultFlags(placeholders=1),
        blocked_by=(BlockedBy(table="usuarios", chunk_id=1),),
    )
    assert result.status == "pending"
    assert result.blocked_by[0].table == "usuarios"
    assert result.flags.placeholders == 1


def test_llm_request_e_response() -> None:
    request = LLMRequest(system="s", prompt="p", max_tokens=10, temperature=0.0)
    response = LLMResponse(text="ok", finish_reason="stop")
    assert request.prompt == "p"
    assert response.text == "ok"


def test_run_context_e_sink_capabilities() -> None:
    run = RunContext(run_id="abc", out_dir="/tmp/out", seed=1)
    capabilities = SinkCapabilities(
        atomic_chunk=True, replace_chunk=True, referential_integrity=False
    )
    receipt = SinkReceipt(sink_ref="chunk-1")
    assert run.seed == 1
    assert capabilities.atomic_chunk is True
    assert receipt.sha256 is None
