"""Resolução de `RunOptions` a partir das flags da CLI, e execução da façade com
drenagem em Ctrl+C (DD-02 §G.3.1, §G.3.2; DD-00 §3.7, §3.8).
"""

from __future__ import annotations

import importlib.metadata
import os
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from datetime import UTC, datetime
from pathlib import Path

from dataipsum.config import RunOptions, SinkConfig, resolve_run_options
from dataipsum.manifest import (
    MANIFEST_FILENAME,
    Manifest,
    compute_schema_sha256,
    write_manifest_atomic,
)
from dataipsum.schema.models import Schema

_DRAIN_SECONDS = 10.0


def build_run_options(
    *, out_dir: Path, sink: SinkConfig, schema: Schema, cli_overrides: dict[str, object]
) -> RunOptions:
    """Funde as flags da CLI (maior precedência) com env `DATAIPSUM_*`, o schema
    e os padrões (§3.8). `out_dir`/`sink` são sempre resolvidos pela CLI."""
    overrides = {"out_dir": out_dir, "sink": sink, **cli_overrides}
    defaults = RunOptions(out_dir=out_dir, sink=sink)
    return resolve_run_options(overrides, dict(os.environ), schema, defaults)


def _write_fallback_partial_manifest(out_dir: Path, schema: Schema, options: RunOptions) -> None:
    """Garante que `dataipsum resume` tenha o que ler quando a chamada é
    interrompida por Ctrl+C sem que a própria façade grave o manifesto.

    Best-effort e temporário: até a trilha D existir, `api.generate`/`api.resume`
    não sabem nada sobre chunks em andamento, então este fallback só grava um
    manifesto `partial` mínimo (sem `chunks`) quando nenhum já existe. Quando o
    driver real existir, ele grava o `partial` de verdade antes de propagar o
    Ctrl+C, e este fallback nunca chega a rodar (o arquivo já existe).
    """
    if (out_dir / MANIFEST_FILENAME).exists():
        return
    schema_dump = schema.model_dump(mode="json", exclude_none=True)
    now = datetime.now(UTC).isoformat()
    manifest = Manifest(
        run_id=str(uuid.uuid4()),
        dataipsum_version=importlib.metadata.version("dataipsum"),
        created_at=now,
        updated_at=now,
        status="partial",
        seed=options.seed if options.seed is not None else 0,
        seed_source="user" if options.seed is not None else "random",
        chunk_size=options.chunk_size or schema.chunk_size,
        schema=schema_dump,
        schema_sha256=compute_schema_sha256(schema_dump),
        sink={"kind": options.sink.kind, "options": options.sink.options},
        plan={},
    )
    write_manifest_atomic(out_dir, manifest)


def run_with_interrupt_drain[T](
    call: Callable[[], T], *, out_dir: Path, schema: Schema, options: RunOptions
) -> T:
    """Roda `call` (uma chamada bloqueante à façade) numa thread e, em Ctrl+C,
    espera até `_DRAIN_SECONDS` pelos chunks em voo antes de gravar o
    manifesto `partial` e propagar a interrupção (§G.3.1).
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future: Future[T] = executor.submit(call)
    try:
        result = future.result()
    except KeyboardInterrupt:
        wait_futures([future], timeout=_DRAIN_SECONDS)
        _write_fallback_partial_manifest(out_dir, schema, options)
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    executor.shutdown(wait=False)
    return result
