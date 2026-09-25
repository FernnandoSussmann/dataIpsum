#!/usr/bin/env bash
# Sink kafka (DD-02, trilha E, M3, E.3.3, E.7). Exige o extra `kafka`:
#   uv sync --extra kafka
#
# Rode a partir desta pasta:
#   docker compose up -d
#   bash gerar.sh
#   uv run python consumidor.py     # verifica key = PK e valor Avro
#   docker compose down -v
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

dataipsum gen \
  --table usuarios --rows 20 \
  --col id:int:pk --col nome:nome_proprio \
  -o "$(pwd)/out/kafka-exemplo" \
  --format kafka \
  --sink-opt bootstrap_servers=localhost:9092 \
  --sink-opt schema_registry_url=http://localhost:8081 \
  --sink-opt topic_prefix=loja. \
  --sink-opt create_topics=true

echo "Saída esperada: tópico 'loja.usuarios' com 20 mensagens, key = id do usuário" \
     "(string) e valor Avro registrado no Schema Registry. Verifique com:" \
     "uv run python examples/sinks/kafka/consumidor.py"
