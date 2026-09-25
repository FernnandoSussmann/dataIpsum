#!/usr/bin/env bash
# `--cpu-max`/`--mem-max` e o log das transições do monitor adaptativo (DD-01 §D.3.4, D.7).
#
# O monitor é sempre ativo (não dá para desligar). Ele amostra CPU/RAM do sistema
# inteiro a cada 1s e ajusta a concorrência com AIMD: reduz pela metade quando o
# teto é ultrapassado em 2 amostras seguidas (com 5s de cooldown), aumenta 1 a 1
# depois de 3 amostras seguidas com folga, e pausa novas submissões sob pressão
# crítica de memória. Rode a partir da raiz do repositório:
#   bash examples/execucao/tetos-de-recursos.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# O comando `generate` é implementado pela trilha D (`dataipsum.execution.orchestrator`)
# e exposto na CLI pela trilha G (DD-02); até lá, este exemplo documenta o comando
# esperado e o que observar no log.
#
#   uv run dataipsum generate \
#     --schema examples/core/seed-fixa.yaml \
#     --out /tmp/saida-tetos \
#     --cpu-max 50 \
#     --mem-max 40
#
# Saída esperada (nível INFO, DD-01 §D.5 item 8 — só contagens, sem dados de linha):
#   INFO dataipsum.execution.resources: monitor: concorrência inicial = 4 (cpu_max=50%)
#   INFO dataipsum.execution.resources: monitor: CPU acima do teto por 2 amostras; concorrência 4 -> 2
#   INFO dataipsum.execution.resources: monitor: folga por 3 amostras; concorrência 2 -> 3
#
# Para reproduzir o monitor isoladamente, sem depender do `generate` de ponta a
# ponta (que precisa das trilhas A/B/C), use `ResourceMonitor` diretamente:
uv run python - <<'PY'
from dataipsum.execution.resources import ResourceMonitor, ResourceSample

monitor = ResourceMonitor(cpu_max=50.0, mem_max=40.0)
print(f"concorrência inicial: {monitor.concurrency}")

# Simula um processo externo consumindo 95% de CPU por 2 amostras seguidas (D-02).
monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=0.0)
monitor.observe(ResourceSample(cpu_percent=95.0, mem_percent=10.0), now=1.0)
print(f"concorrência após pressão de CPU: {monitor.concurrency}")

# A CPU volta a ficar livre: depois de 3 amostras de folga, a concorrência sobe de novo.
for t in (10.0, 11.0, 12.0):
    monitor.observe(ResourceSample(cpu_percent=5.0, mem_percent=10.0), now=t)
print(f"concorrência após a folga: {monitor.concurrency}")
PY
