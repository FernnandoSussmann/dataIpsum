#!/usr/bin/env bash
# `--emit-schema ddl,avro` durante a geração (DD-02 §F.3.3, §F.7).
#
# O orquestrador (trilha D, DD-01) chama `api.export_schema` para
# `<out>/_schema/ddl/` e `<out>/_schema/avro/`, e registra cada arquivo em
# `manifest.emitted_schemas` com sha256 (DD-00 §3.7). Até a trilha D existir:
#   dataipsum gen examples/schema-io/loja.yaml -o /tmp/saida --emit-schema ddl,avro --dialect postgres
#
# Demonstração equivalente, direto da biblioteca (o que a trilha D chamará por dentro):
set -euo pipefail

OUT_DIR="${1:-/tmp/dataipsum-emit-schema}"

uv run python -c "
import hashlib
from pathlib import Path
from dataipsum.schema.loader import load_schema
from dataipsum.schema_io import export_schema

schema = load_schema(Path('examples/schema-io/loja.yaml'))
ddl_paths = export_schema(schema, 'ddl', 'postgres', out_dir=Path('$OUT_DIR') / '_schema' / 'ddl')
avro_paths = export_schema(schema, 'avro', out_dir=Path('$OUT_DIR') / '_schema' / 'avro')

for path in [*ddl_paths, *avro_paths]:
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f'{path}: sha256={sha256}')
"

echo "Schemas emitidos em: $OUT_DIR/_schema/{ddl,avro}/"
