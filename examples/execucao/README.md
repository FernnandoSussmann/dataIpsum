# Exemplos da área `execucao` (DD-01, Trilha D — DD-01 §D.7)

Cada exemplo abaixo demonstra uma feature opcional da trilha D: orquestrador,
executor local, monitor adaptativo, `LLMLimiter`, `resume` e o executor Ray (M2).
O motor (`dataipsum.api.generate`/`resume`, sobre `dataipsum.execution.orchestrator`)
já está implementado nesta branch (DD-01 §S5); a CLI `dataipsum gen`/`dataipsum resume`
em si é da trilha G (DD-02) e não está nesta branch. Até o merge das duas, cada
exemplo mostra o comando esperado **e** como exercitar a mesma lógica hoje,
direto pela biblioteca ou pelos testes.

| Arquivo | Demonstra | Como rodar hoje |
|---|---|---|
| [`tetos-de-recursos.sh`](tetos-de-recursos.sh) | `--cpu-max`/`--mem-max` e as transições do monitor adaptativo (AIMD) | `bash examples/execucao/tetos-de-recursos.sh` |
| [`resume.sh`](resume.sh) | Interromper (Ctrl+C) e retomar com `dataipsum resume`, sem replanejar | `bash examples/execucao/resume.sh` |
| [`llm-concorrencia.yaml`](llm-concorrencia.yaml) | `max_concurrency` por provedor LLM (`LLMLimiter` entre processos) | `uv run python -c "from dataipsum import load_schema; load_schema('examples/execucao/llm-concorrencia.yaml')"` |
| [`ray-local.sh`](ray-local.sh) | Cluster Ray local de 1 nó (`ray start --head`) + `RayExecutor` (M2, requer `[ray]`) | `bash examples/execucao/ray-local.sh` (depois de `uv sync --extra ray`) |
| [`ray-cluster/`](ray-cluster/) | Docker compose com head + 2 workers na mesma imagem (`EXTRAS=ray`), um deles com `--resources='{"llm": 1}'`, rede interna sem portas públicas | `docker compose -f examples/execucao/ray-cluster/docker-compose.yml up` |

## Por que "como rodar hoje" e não só o comando da CLI

A trilha D foi escrita em paralelo com as trilhas A (tipos), B (relações) e C
(LLM) — DD-01 §0 — e os exemplos abaixo foram criados nessa fase, contra
fakes. A integração S5 já trocou os fakes pelas implementações reais
(`dataipsum.api.generate`/`resume` funcionam de ponta a ponta, ver
`tests/integration/motor/`), mas a CLI (trilha G, DD-02) ainda não está nesta
branch, então os comandos `dataipsum gen`/`dataipsum resume` comentados em
cada exemplo continuam sendo o comando **esperado**, a rodar depois do merge
com o DD-02. Por isso os exemplos também mostram como exercitar a mesma
lógica hoje, direto pela biblioteca ou pelos testes:

- `ResourceMonitor`/`ProcessLLMLimiter` diretamente;
- `dataipsum.execution.orchestrator._execute`/`generate`/`resume` com um
  `FakeExecutor`/`FakePlanner` (`dataipsum.testing`), exatamente como
  `tests/execution/unit/test_orchestrator.py`, ou com o `RelationsPlanner`/
  `LocalExecutor` reais, como `tests/integration/motor/`;
- para o Ray (M2), o `RayExecutor` real, que só precisa de um cluster Ray vivo.

## M1 vs. M2

`tetos-de-recursos.sh`, `resume.sh` e `llm-concorrencia.yaml` são M1 (executor
local) e não precisam de nada além de `uv sync`. `ray-local.sh` e
`ray-cluster/` são M2 e precisam do extra opcional `[ray]`
(`uv sync --extra ray`) — que **ainda não existe** em `pyproject.toml` neste
worktree, porque a trilha D não pode editar esse arquivo (DD-01 §0). Ver o
relatório do worktree para a mudança de contrato pendente.
