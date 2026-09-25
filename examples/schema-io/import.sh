#!/usr/bin/env bash
# Import de DDL com PK, FK, ponte (many_to_many), email e cpf (DD-02 §F.3.4, §F.7, §F.9).
#
# Com a CLI completa (trilha G, DD-02):
#   dataipsum schema import examples/schema-io/import/loja.sql --dialect postgres -o /tmp/loja.yaml
#
# Até a CLI expor `schema import`, o mesmo resultado sai direto da biblioteca. O SQL nunca é
# executado e nenhuma conexão é aberta (F.5).
set -euo pipefail

OUT_FILE="${1:-/tmp/dataipsum-import/loja.yaml}"
mkdir -p "$(dirname "$OUT_FILE")"

uv run python -c "
import sys
import yaml
from pathlib import Path
from dataipsum.schema_io import import_ddl

sql_text = Path('examples/schema-io/import/loja.sql').read_text(encoding='utf-8')
schema, report = import_ddl(sql_text, 'postgres')

comment_block = report.render_yaml_comment_block()
body = yaml.safe_dump(
    schema.model_dump(mode='json', exclude_none=True), allow_unicode=True, sort_keys=False
)
Path('$OUT_FILE').write_text(comment_block + body, encoding='utf-8')
sys.stderr.write(comment_block)
"

echo "Schema importado em: $OUT_FILE (revise o bloco 'Revise:' no topo do arquivo)"
