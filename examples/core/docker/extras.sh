#!/usr/bin/env bash
# Constrói a imagem com extras (ray, postgres, kafka) e mostra a MESMA imagem rodando como
# worker Ray (DD-00 §3.12.1: "mesma imagem para todos os papéis... não há imagens divergentes
# entre os nós"). Rode a partir da raiz do repositório:
#   bash examples/core/docker/extras.sh
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

IMAGE="dataipsum:extras"
VERSION="$(uv run python -c 'import importlib.metadata as m; print(m.version("dataipsum"))')"

docker build \
  --build-arg VERSION="$VERSION" \
  --build-arg EXTRAS="ray,postgres,kafka" \
  -t "$IMAGE" \
  .

# Papel 1: CLI normal (entrypoint padrão `dataipsum`).
docker run --rm "$IMAGE" --version

# Papel 2: a mesma imagem como worker Ray, trocando só o entrypoint na invocação
# (nenhum ARG/ENV de imagem muda; ver DD-01 trilha D para o fragmento `execucao.runtime`).
docker run --rm \
  --entrypoint ray \
  "$IMAGE" \
  start --head --disable-usage-stats --block &
RAY_PID=$!

sleep 5
kill "$RAY_PID" 2>/dev/null || true
