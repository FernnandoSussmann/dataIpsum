#!/usr/bin/env bash
# Retoma a execução de `falha-placeholder.yaml` depois que o provedor volta ao ar
# (DD-01 §C.7). `dataipsum resume` reprocessa os chunks `pending_llm`/`failed`; as colunas
# determinísticas saem idênticas (mesma seed) e os chunks com placeholder são substituídos
# atomicamente pelo texto real, com `is_placeholder` voltando a `false`.
set -euo pipefail

OUT_DIR="${1:-/tmp/saida-placeholder}"

echo "Retomando a execução em '${OUT_DIR}'..."
uv run dataipsum resume --out "${OUT_DIR}"
echo "Pronto: confira o manifesto em '${OUT_DIR}/_manifest.json' (status deve ser 'done')."
