#!/usr/bin/env bash
# Sink csv com opções (DD-02, trilha E, E.7): delimiter, null_value e escape_formulas.
#
# A CLI completa é entregue pela trilha G (DD-02); até lá, este script documenta o
# comando esperado. Rode a partir da raiz do repositório:
#   bash examples/sinks/csv-opcoes.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

OUT_DIR="$(pwd)/out/csv-opcoes"
rm -rf "$OUT_DIR"

dataipsum gen \
  --table usuarios \
  --rows 20 \
  --col id:int:pk \
  --col nome:nome_proprio \
  --col bio:string:max_length=50 \
  -o "$OUT_DIR" \
  --format csv \
  --sink-opt delimiter=';' \
  --sink-opt null_value=NULL \
  --sink-opt escape_formulas=true

echo "Saída esperada: $OUT_DIR/usuarios/part-00001.csv com campos separados por ';'," \
     "nulos como a palavra NULL, e qualquer valor começando com =, +, - ou @" \
     "prefixado por uma aspa simples (proteção contra fórmulas em planilhas)."
