#!/usr/bin/env bash
# Constrói a imagem base do dataIpsum (sem extras) e gera dados a partir de um schema local.
#
# DD-00 §3.12.1: mesma imagem para todos os papéis; schema montado em /schemas (somente
# leitura) e saída em /out (volume gravável). Rode a partir da raiz do repositório:
#   bash examples/core/docker/basico.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

IMAGE="dataipsum:local"
SCHEMA_DIR="$(pwd)/examples"
OUT_DIR="$(pwd)/out"

docker build \
  --build-arg VERSION="$(uv run python -c 'import importlib.metadata as m; print(m.version("dataipsum"))')" \
  -t "$IMAGE" \
  .

mkdir -p "$OUT_DIR"

# `generate` é implementado pela trilha G (DD-02); até lá, `--help` é o comando de referência.
docker run --rm \
  -v "$SCHEMA_DIR:/schemas:ro" \
  -v "$OUT_DIR:/out" \
  "$IMAGE" \
  generate --schema /schemas/loja.yaml --out /out
