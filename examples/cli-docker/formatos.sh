#!/usr/bin/env bash
# `--format csv/jsonl/parquet` com `--sink-opt` (DD-02 §G.3.1). Rode a partir
# da raiz do repositório:
#   bash examples/cli-docker/formatos.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

for format in csv jsonl parquet; do
  echo "== --format ${format} =="
  uv run dataipsum gen \
    --table usuarios \
    --rows 5 \
    --col "id:int:pk" \
    --col "nome:nome_proprio" \
    -o "/tmp/dataipsum-formatos-exemplo-${format}" \
    --format "${format}" \
    --sink-opt "compression=none" || true
  echo
done

echo "== --sink-opt com segredo é recusado (nunca aceite --password) =="
uv run dataipsum gen \
  --table usuarios --rows 1 --col "id:int:pk" \
  -o /tmp/dataipsum-formatos-exemplo-postgres \
  --format postgres \
  --sink-opt "password=nao-faca-isso" || true

echo
echo "== a forma aceita: '*_env' com o NOME da variável, nunca o segredo =="
uv run dataipsum gen \
  --table usuarios --rows 1 --col "id:int:pk" \
  -o /tmp/dataipsum-formatos-exemplo-postgres \
  --format postgres \
  --sink-opt "password_env=PG_PASSWORD" || true
