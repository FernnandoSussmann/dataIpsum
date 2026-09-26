"""Função `run_chunk` picklable executada em cada worker (DD-01 §D.3.2, §D.3.3).

`LocalExecutor`/`RayExecutor` recebem só a função (nunca estado global): cada chamada reconstrói
`Registry`, `Planner` e `Sink` a partir do `ChunkTask`, que é autocontido. É a "integração S5"
citada no docstring de `dataipsum.execution.local_executor`.

Este módulo monta sempre a implementação de produção (registry real via `build_registry`,
`RelationsPlanner`, provedores LLM reais). Testes/integração que precisam de `FakeSink`/
`FakeLLM`/`FakeToxicity` (DD-01 §3, "não depende do DD-02") montam o próprio `run_chunk`, sem
depender deste módulo — ver `tests/integration/motor/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from dataipsum.contracts.executor import ChunkResult
from dataipsum.execution import chunk_builder
from dataipsum.execution.llm_engine import build_llm_engine
from dataipsum.registry import build_registry
from dataipsum.relations import RelationsPlanner

if TYPE_CHECKING:
    from dataipsum.contracts.executor import ChunkTask
    from dataipsum.contracts.generator import Generator
    from dataipsum.contracts.sink import Sink
    from dataipsum.registry import Registry


def run_chunk(task: ChunkTask) -> ChunkResult:
    """Reconstrói `Registry`/`Planner`/`Sink`/motor LLM a partir de `task` e constrói o chunk.

    Roda dentro do worker (processo `spawn`, DD-01 §D.3.3): não pode depender de estado
    herdado do processo pai. `planner.plan` é reexecutado aqui só para popular o estado interno
    do `Planner` (`pk_at`/`row_at`); o `chunk_size` usado não precisa ser o mesmo da geração do
    `RunPlan` original (que já aconteceu no driver) — `pk_at`/`row_at` são função só do total de
    linhas de cada tabela e das seeds, não de como elas foram fatiadas em chunks.
    """
    registry = build_registry()
    generators = {
        name: cast("type[Generator]", generator_cls)()
        for name, generator_cls in registry.generators.items()
    }
    planner = RelationsPlanner(generators=generators)
    planner.plan(task.schema, task.root_seed, task.schema.chunk_size)

    cache_dir_raw = task.run_options.get("cache_dir")
    cache_dir = Path(cast("str", cache_dir_raw)) if cache_dir_raw is not None else None
    engine = build_llm_engine(task.schema, registry, cache_dir=cache_dir)

    sink = _build_sink(registry, task.sink_options)
    return chunk_builder.build_chunk(
        task, planner=planner, registry=registry, sink=sink, llm_engine=engine
    )


def _build_sink(registry: Registry, sink_options: dict[str, object]) -> Sink | None:
    kind = sink_options.get("kind")
    if not kind:
        return None
    sink_cls = cast("type[Sink]", registry.get_sink(str(kind)))
    options = cast("dict[str, object]", sink_options.get("options", {}))
    return sink_cls(**options)
