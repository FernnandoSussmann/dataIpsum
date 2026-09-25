# Exemplos da área `execucao` (DD-01, Trilha D — DD-01 §D.7)

Cada exemplo abaixo demonstra uma feature opcional da trilha D: orquestrador,
executor local, monitor adaptativo, `LLMLimiter`, `resume` e o executor Ray (M2).
O comando `dataipsum generate`/`dataipsum resume` é implementado por
`dataipsum.execution.orchestrator` (`generate`/`resume`) e exposto na CLI pela
trilha G (DD-02); até lá, cada exemplo mostra o comando esperado **e** como
exercitar a mesma lógica hoje, direto pela biblioteca ou pelos testes.

| Arquivo | Demonstra | Como rodar hoje |
|---|---|---|
| [`tetos-de-recursos.sh`](tetos-de-recursos.sh) | `--cpu-max`/`--mem-max` e as transições do monitor adaptativo (AIMD) | `bash examples/execucao/tetos-de-recursos.sh` |
| [`resume.sh`](resume.sh) | Interromper (Ctrl+C) e retomar com `dataipsum resume`, sem replanejar | `bash examples/execucao/resume.sh` |
| [`llm-concorrencia.yaml`](llm-concorrencia.yaml) | `max_concurrency` por provedor LLM (`LLMLimiter` entre processos) | `uv run python -c "from dataipsum import load_schema; load_schema('examples/execucao/llm-concorrencia.yaml')"` |
| [`ray-local.sh`](ray-local.sh) | Cluster Ray local de 1 nó (`ray start --head`) + `RayExecutor` (M2, requer `[ray]`) | `bash examples/execucao/ray-local.sh` (depois de `uv sync --extra ray`) |
| [`ray-cluster/`](ray-cluster/) | Docker compose com head + 2 workers na mesma imagem (`EXTRAS=ray`), um deles com `--resources='{"llm": 1}'`, rede interna sem portas públicas | `docker compose -f examples/execucao/ray-cluster/docker-compose.yml up` |

## Por que "como rodar hoje" e não só o comando da CLI

A trilha D roda em paralelo com as trilhas A (tipos), B (relações) e C (LLM) —
DD-01 §0. Sem um `Planner` real (trilha B) nem geradores reais (trilha A), um
`generate()` de ponta a ponta com um schema de verdade não é possível ainda
neste worktree. Por isso os exemplos usam:

- `ResourceMonitor`/`ProcessLLMLimiter` diretamente (não dependem de A/B/C);
- `dataipsum.execution.orchestrator._execute`/`generate`/`resume` com um
  `FakeExecutor`/`FakePlanner` (`dataipsum.testing`), exatamente como
  `tests/execution/unit/test_orchestrator.py`;
- para o Ray (M2), o `RayExecutor` real, que só precisa de um cluster Ray vivo
  (não dos geradores da trilha A).

Quando a integração S5 (DD-01 §3) trocar os fakes pelas implementações reais,
os comandos `dataipsum generate --schema ... --out ...` comentados em cada
exemplo passam a funcionar sem alterações.

## M1 vs. M2

`tetos-de-recursos.sh`, `resume.sh` e `llm-concorrencia.yaml` são M1 (executor
local) e não precisam de nada além de `uv sync`. `ray-local.sh` e
`ray-cluster/` são M2 e precisam do extra opcional `[ray]`
(`uv sync --extra ray`) — que **ainda não existe** em `pyproject.toml` neste
worktree, porque a trilha D não pode editar esse arquivo (DD-01 §0). Ver o
relatório do worktree para a mudança de contrato pendente.
