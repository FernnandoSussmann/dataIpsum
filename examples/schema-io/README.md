# Exemplos da trilha F — import e export de schema (DD-02)

Cada exemplo abaixo demonstra uma feature opcional da trilha F (§F.7 "Exemplos de
features opcionais"). Os comandos `dataipsum schema export`/`dataipsum schema import`
são expostos pela CLI (trilha G, DD-02); até lá, cada script chama
`dataipsum.schema_io` diretamente (a mesma implementação que a CLI vai chamar) e
documenta, no comentário do topo, o comando final esperado.

| Arquivo | Demonstra | Comando (CLI final) | Saída esperada |
|---|---|---|---|
| [`export-ddl-postgres.sh`](export-ddl-postgres.sh) | `ddl_for(schema, "postgres")` | `dataipsum schema export loja.yaml --format ddl --dialect postgres -o DIR` | `DIR/postgres.sql` com um `CREATE TABLE` por tabela, em ordem topológica |
| [`export-ddl-mysql.sh`](export-ddl-mysql.sh) | o mesmo em MySQL | `dataipsum schema export loja.yaml --format ddl --dialect mysql -o DIR` | `DIR/mysql.sql` |
| [`export-avro.sh`](export-avro.sh) | `avro_schema(schema, table)` | `dataipsum schema export loja.yaml --format avro -o DIR` | um `DIR/<tabela>.avsc` por tabela, todos aceitos por `fastavro.parse_schema` |
| [`emit-schema.sh`](emit-schema.sh) | `--emit-schema ddl,avro` durante a geração | `dataipsum gen loja.yaml -o OUT --emit-schema ddl,avro --dialect postgres` | arquivos em `OUT/_schema/{ddl,avro}/`, cada um com seu sha256 (registrado no manifesto pela trilha D) |
| [`import/loja.sql`](import/loja.sql) + [`import.sh`](import.sh) | `import_ddl(sql_text, "postgres")`: PK serial, FK 1:N, ponte `many_to_many`, inferência de `cpf`/`email`/`nome_proprio` | `dataipsum schema import import/loja.sql --dialect postgres -o loja-importado.yaml` | YAML válido, começando com um bloco `# Revise:` que lista cada inferência e TODO |
| [`loja.yaml`](loja.yaml) | Schema de referência usado pelos exemplos de export acima | — | cópia local mínima do exemplo do DD-00 §3.3 (quando `examples/loja.yaml` da trilha H existir no repositório integrado, os mesmos comandos funcionam apontando para ele) |

## Executando

```bash
bash examples/schema-io/export-ddl-postgres.sh /tmp/ddl-postgres
bash examples/schema-io/export-ddl-mysql.sh /tmp/ddl-mysql
bash examples/schema-io/export-avro.sh /tmp/avro
bash examples/schema-io/emit-schema.sh /tmp/emit
bash examples/schema-io/import.sh /tmp/loja-importado.yaml
```

## Inspecionando sem os scripts

```bash
uv run python -c "
from pathlib import Path
from dataipsum.schema.loader import load_schema
from dataipsum.schema_io import ddl_for, avro_schema, import_ddl

schema = load_schema(Path('examples/schema-io/loja.yaml'))
print(ddl_for(schema, 'postgres'))
print(avro_schema(schema, 'usuarios'))

sql_text = Path('examples/schema-io/import/loja.sql').read_text()
imported_schema, report = import_ddl(sql_text, 'postgres')
print(report.render_yaml_comment_block())
"
```

## Garantias verificadas pelos testes (`tests/schema_io/`)

- O SQL de `import/loja.sql` **nunca é executado**: `import_ddl` só chama
  `sqlglot.parse` sobre o texto, e nenhum módulo de driver (`psycopg`, `pymysql`)
  é importado (DD-02 §F.5).
- O DDL exportado re-parseia no mesmo dialeto (`sqlglot.parse`) e, nos testes de
  integração (`tests/schema_io/integration/`, marcador `integration`), executa
  sem erro em Postgres 16 e MySQL 8 reais (via `testcontainers`).
- Cada `.avsc` exportado é aceito por `fastavro.parse_schema` (dependência de dev).
