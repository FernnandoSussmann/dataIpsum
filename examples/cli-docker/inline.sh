#!/usr/bin/env bash
# Geração rápida de uma tabela via flags inline (DD-02 §G.3.1, gramática
# `nome:tipo[:pk][:chave=valor...]`), e `--print-schema` para inspecionar o
# YAML equivalente sem gerar nada. Rode a partir da raiz do repositório:
#   bash examples/cli-docker/inline.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== --print-schema (não gera nada, só mostra o YAML equivalente) =="
uv run dataipsum gen \
  --table usuarios \
  --rows 10 \
  --col "id:int:pk" \
  --col "nome:nome_proprio:max_length=80" \
  --col "bio:string:max_length=200:null_ratio=0.1" \
  -o /tmp/dataipsum-inline-exemplo \
  --print-schema

echo
echo "== geração de verdade (falha até a trilha D existir; ver README.md) =="
uv run dataipsum gen \
  --table usuarios \
  --rows 10 \
  --col "id:int:pk" \
  --col "nome:nome_proprio" \
  -o /tmp/dataipsum-inline-exemplo \
  --format csv || true
