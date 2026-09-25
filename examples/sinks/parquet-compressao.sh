#!/usr/bin/env bash
# Compressão do sink parquet (DD-02, trilha E, E.7): snappy x zstd (padrão).
#
# Rode a partir da raiz do repositório:
#   bash examples/sinks/parquet-compressao.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

OUT_DIR="$(pwd)/out/parquet-compressao"
rm -rf "$OUT_DIR"

dataipsum gen \
  --table usuarios --rows 5000 \
  --col id:int:pk --col nome:nome_proprio --col bio:string:max_length=200 \
  -o "$OUT_DIR/zstd" --format parquet --sink-opt compression=zstd

dataipsum gen \
  --table usuarios --rows 5000 \
  --col id:int:pk --col nome:nome_proprio --col bio:string:max_length=200 \
  -o "$OUT_DIR/snappy" --format parquet --sink-opt compression=snappy

echo "Saída esperada: os dois diretórios têm o mesmo conteúdo lógico (mesmas 5000" \
     "linhas), mas $OUT_DIR/zstd/usuarios/part-00001.parquet costuma ser menor que" \
     "$OUT_DIR/snappy/usuarios/part-00001.parquet (zstd comprime mais, ao custo de" \
     "mais CPU na escrita)."
