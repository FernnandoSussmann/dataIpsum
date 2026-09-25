#!/usr/bin/env bash
# Interromper (Ctrl+C) e retomar com `dataipsum resume` (DD-01 §D.3.5, §D.5, D.7).
#
# Ctrl+C durante uma geração: o driver para de submeter novos chunks, espera até
# 10s pelos chunks já em voo e grava o manifesto com `status: partial`.
# `dataipsum resume <out>` lê esse manifesto, reusa o `RunPlan`/seed gravados (sem
# replanejar) e reexecuta só os chunks `pending`/`failed`/`pending_llm`.
# Rode a partir da raiz do repositório:
#   bash examples/execucao/resume.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# O comando `generate`/`resume` é implementado pela trilha D e exposto na CLI pela
# trilha G (DD-02); até lá, este exemplo documenta o fluxo esperado:
#
#   uv run dataipsum generate --schema examples/core/limites.yaml --out /tmp/saida-resume &
#   PID=$!
#   sleep 2 && kill -INT "$PID"   # simula Ctrl+C
#   wait "$PID" || true
#   cat /tmp/saida-resume/_manifest.json | python3 -m json.tool | grep '"status"'
#   # -> "status": "partial"
#
#   uv run dataipsum resume /tmp/saida-resume
#   cat /tmp/saida-resume/_manifest.json | python3 -m json.tool | grep '"status"'
#   # -> "status": "completed"
#
# O agendamento (D.3.1/D.3.5) e o Ctrl+C podem ser exercitados hoje, sem CLI nem
# sinks reais, usando `execution.orchestrator` com um `FakeExecutor` que simula a
# interrupção e um `FakeSink` em memória (é exatamente o que
# `tests/execution/unit/test_orchestrator.py::test_ctrl_c_para_de_submeter_e_grava_partial`
# e `::test_resume_reexecuta_so_os_nao_done` fazem).
uv run pytest tests/execution/unit/test_orchestrator.py \
  -k "ctrl_c or resume_reexecuta" -v
