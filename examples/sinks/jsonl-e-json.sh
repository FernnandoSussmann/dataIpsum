#!/usr/bin/env bash
# Diferença entre os sinks jsonl e json (DD-02, trilha E, E.7, E.3.1).
#
# `jsonl`: um objeto JSON por linha (padrão para "JSON"). `json`: um array JSON por
# arquivo. Rode a partir da raiz do repositório:
#   bash examples/sinks/jsonl-e-json.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

OUT_DIR="$(pwd)/out/jsonl-e-json"
rm -rf "$OUT_DIR"

dataipsum gen \
  --table usuarios --rows 5 \
  --col id:int:pk --col nome:nome_proprio \
  -o "$OUT_DIR/jsonl" --format jsonl

dataipsum gen \
  --table usuarios --rows 5 \
  --col id:int:pk --col nome:nome_proprio \
  -o "$OUT_DIR/json" --format json

echo "Saída esperada:"
echo "  $OUT_DIR/jsonl/usuarios/part-00001.jsonl: 5 linhas, uma por objeto JSON."
echo "  $OUT_DIR/json/usuarios/part-00001.json: um único array JSON com 5 objetos."
