#!/usr/bin/env bash
# Export de DDL MySQL a partir de um schema dataIpsum (DD-02 §F.3.3, §F.7).
#
# Com a CLI completa (trilha G, DD-02):
#   dataipsum schema export examples/schema-io/loja.yaml --format ddl --dialect mysql -o /tmp/ddl
#
# Até a CLI expor `schema export`, o mesmo resultado sai direto da biblioteca:
set -euo pipefail

OUT_DIR="${1:-/tmp/dataipsum-ddl-mysql}"

uv run python -c "
from pathlib import Path
from dataipsum.schema.loader import load_schema
from dataipsum.schema_io import export_schema

schema = load_schema(Path('examples/schema-io/loja.yaml'))
paths = export_schema(schema, 'ddl', 'mysql', out_dir=Path('$OUT_DIR'))
for path in paths:
    print(path)
"

echo "DDL MySQL em: $OUT_DIR/mysql.sql"
