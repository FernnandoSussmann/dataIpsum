#!/usr/bin/env bash
# Sink postgres (DD-02, trilha E, M3, E.3.2, E.7). Exige o extra `postgres`:
#   uv sync --extra postgres
#
# Rode a partir desta pasta:
#   docker compose up -d
#   bash gerar.sh
#   docker compose down -v
set -euo pipefail

export PG_DSN="postgresql://dataipsum:dataipsum@localhost:5432/dataipsum?sslmode=disable"

cd "$(git rev-parse --show-toplevel)"

dataipsum gen \
  --table usuarios --rows 100 \
  --col id:int:pk --col nome:nome_proprio \
  -o "$(pwd)/out/postgres-exemplo" \
  --format postgres \
  --sink-opt dsn_env=PG_DSN \
  --sink-opt create_tables=true

echo "Saída esperada: a tabela 'usuarios' no banco 'dataipsum' com 100 linhas, e a" \
     "tabela de controle '_dataipsum_chunks' com uma linha 'committed' por chunk." \
     "Rodar este script de novo não duplica linhas (E-04): a escrita é idempotente" \
     "por chunk, controlada pela tabela '_dataipsum_chunks'."
