#!/usr/bin/env bash
# Valida um schema dataIpsum com uma ferramenta EXTERNA de JSON Schema,
# usando o contrato versionado em `schemas/dataipsum-schema.v1.json`
# (DD-02, trilha H, H.3.1/H.6). Isso prova que o contrato é consumível por
# qualquer cliente (a futura UI web, por exemplo) sem depender do pacote
# dataIpsum em si.
#
# Requer a CLI `check-jsonschema` (https://github.com/python-jsonschema/check-jsonschema),
# instalável com `uv tool install check-jsonschema` ou `pipx install check-jsonschema`.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JSON_SCHEMA="${REPO_ROOT}/schemas/dataipsum-schema.v1.json"
ALVO="${1:-${REPO_ROOT}/examples/contrato/schema.json}"

if ! command -v check-jsonschema >/dev/null 2>&1; then
    echo "check-jsonschema não encontrado. Instale com: uv tool install check-jsonschema" >&2
    exit 1
fi

echo "Validando '${ALVO}' contra '${JSON_SCHEMA}'..."
check-jsonschema --schemafile "${JSON_SCHEMA}" "${ALVO}"
echo "OK: schema válido segundo o contrato dataIpsum v1."
