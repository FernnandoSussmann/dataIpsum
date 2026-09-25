#!/usr/bin/env bash
# Export de Avro Schema (um .avsc por tabela, DD-02 §F.3.2, §F.7).
#
# Com a CLI completa (trilha G, DD-02):
#   dataipsum schema export examples/schema-io/loja.yaml --format avro -o /tmp/avro
#
# Até a CLI expor `schema export`, o mesmo resultado sai direto da biblioteca:
set -euo pipefail

OUT_DIR="${1:-/tmp/dataipsum-avro}"

uv run python -c "
from pathlib import Path
from dataipsum.schema.loader import load_schema
from dataipsum.schema_io import export_schema

schema = load_schema(Path('examples/schema-io/loja.yaml'))
paths = export_schema(schema, 'avro', out_dir=Path('$OUT_DIR'))
for path in paths:
    print(path)
"

echo "Avro Schemas em: $OUT_DIR/*.avsc"
