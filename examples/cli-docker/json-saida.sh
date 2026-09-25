#!/usr/bin/env bash
# `--json` para automação: stdout fica limpo com um único objeto JSON (sucesso
# ou erro), e todo log/progresso vai para o stderr (DD-02 §G.3.1). Rode a
# partir da raiz do repositório:
#   bash examples/cli-docker/json-saida.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== stdout (só o JSON) =="
uv run dataipsum gen \
  --table usuarios --rows 3 --col "id:int:pk" \
  -o /tmp/dataipsum-json-exemplo \
  --format csv \
  --json \
  2>/tmp/dataipsum-json-exemplo.stderr.log \
  | tee /tmp/dataipsum-json-exemplo.stdout.json || true

echo
echo "== validando que o stdout é JSON (mesmo em erro, com status:error) =="
uv run python -c "import json,sys; print(json.load(open('/tmp/dataipsum-json-exemplo.stdout.json')))"

echo
echo "== stderr (progresso/erros; vazio ou com mensagens, nunca o JSON) =="
cat /tmp/dataipsum-json-exemplo.stderr.log
