#!/usr/bin/env bash
# Sink mysql (DD-02, trilha E, M3, E.3.2, E.7). Exige o extra `mysql`:
#   uv sync --extra mysql
#
# Rode a partir desta pasta:
#   docker compose up -d
#   bash gerar.sh
#   docker compose down -v
set -euo pipefail

export MYSQL_DSN="mysql://dataipsum:dataipsum@localhost:3306/dataipsum"

cd "$(git rev-parse --show-toplevel)"

dataipsum gen \
  --table usuarios --rows 100 \
  --col id:int:pk --col nome:nome_proprio \
  -o "$(pwd)/out/mysql-exemplo" \
  --format mysql \
  --sink-opt dsn_env=MYSQL_DSN \
  --sink-opt create_tables=true

echo "Saída esperada: a tabela 'usuarios' com 100 linhas via INSERT em lotes" \
     "(local_infile desligado, DD-02 E.3.2/E.5.3), e '_dataipsum_chunks' com uma" \
     "linha 'committed' por chunk. Rodar de novo não duplica linhas (E-04)."
