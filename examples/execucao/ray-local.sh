#!/usr/bin/env bash
# Cluster Ray local de 1 nó (`ray start --head`) + `--executor ray` (DD-01 §D.3.6, D.7, M2).
#
# Requer o extra opcional `[ray]` (`uv sync --extra ray`) — este worktree (trilha D) não
# pode editar `pyproject.toml`, então esse extra ainda não existe no `pyproject.toml` do
# repositório principal; ver o relatório do worktree sobre a mudança de contrato pendente.
# Rode a partir da raiz do repositório, DEPOIS de instalar o extra:
#   bash examples/execucao/ray-local.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if ! uv run python -c "import ray" 2>/dev/null; then
  echo "ray não instalado; rode 'uv sync --extra ray' primeiro (extra ainda não existe" \
       "em pyproject.toml neste worktree — ver relatório da trilha D)." >&2
  exit 1
fi

RAY_USAGE_STATS_ENABLED=0 uv run ray start --head --num-cpus 2

# O comando `gen` é implementado pela trilha D; a flag `--executor ray` seleciona
# `execution.ray_executor.RayExecutor` (D.3.6). Até a CLI existir (trilha G), o executor
# Ray pode ser exercitado diretamente:
uv run python - <<'PY'
from dataipsum.execution.ray_executor import RayExecutor


def run_chunk(task):
    from dataipsum.contracts.executor import ChunkResult

    return ChunkResult(table=task.table, chunk_id=task.chunk_spec.id, status="done", rows=task.chunk_spec.rows)


executor = RayExecutor(ray_address="auto", run_chunk=run_chunk)
print(f"concorrência (slots dos nós vivos): {executor.concurrency}")
executor.shutdown(wait=True)
PY

uv run ray stop
