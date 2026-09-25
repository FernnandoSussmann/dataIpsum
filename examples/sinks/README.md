# Exemplos da área `sinks` (DD-02, trilha E)

Cada exemplo abaixo demonstra uma opção ou um sink opcional da trilha E (§3.2 do
DD-00, "Regra transversal: exemplos de features opcionais"). `tests/contract/
test_examples.py` (trilha H) valida os schemas/YAML deste diretório com
`dataipsum.validate` quando existirem; os scripts `.sh`/`.py` aqui documentam o
comando de CLI esperado (a CLI completa é entregue pela trilha G, DD-02).

| Arquivo | Demonstra | Extra necessário | Saída esperada |
|---|---|---|---|
| [`csv-opcoes.sh`](csv-opcoes.sh) | `--format csv` com `delimiter=;`, `null_value=NULL`, `escape_formulas=true` | nenhum | `usuarios/part-00001.csv` com `;` como separador, `NULL` para nulos e `'` antes de valores que começam com `=`, `+`, `-` ou `@` |
| [`jsonl-e-json.sh`](jsonl-e-json.sh) | diferença entre `jsonl` (um objeto por linha) e `json` (um array por arquivo) | nenhum | `jsonl/usuarios/part-00001.jsonl` com 5 linhas; `json/usuarios/part-00001.json` com um array de 5 objetos |
| [`parquet-compressao.sh`](parquet-compressao.sh) | `compression=snappy` × `zstd` (padrão) | nenhum | dois diretórios com os mesmos dados, tamanhos de arquivo diferentes |
| [`postgres/`](postgres/) | sink `postgres`: `COPY`, tabela de controle `_dataipsum_chunks`, `create_tables=true` | `postgres` | ver [`postgres/README.md`](postgres/README.md) |
| [`mysql/`](mysql/) | sink `mysql`: `INSERT` em lotes, `local_infile` desligado | `mysql` | ver [`mysql/README.md`](mysql/README.md) |
| [`kafka/`](kafka/) | sink `kafka`: producer idempotente, Avro via Schema Registry, key = PK | `kafka` | ver [`kafka/README.md`](kafka/README.md) |

## Pré-requisitos gerais

- Python 3.12+ e `uv` (para instalar os extras: `uv sync --extra postgres --extra
  mysql --extra kafka`, ou um extra por vez);
- Docker + Docker Compose, só para os exemplos `postgres/`, `mysql/` e `kafka/`
  (cada um sobe seu próprio banco/broker descartável, isolado do compose de dev
  da raiz do repositório, que é da trilha G).

## Enquanto a CLI completa (trilha G) não existe

Os scripts `.sh` acima chamam `dataipsum gen ...`, que é implementado pela
trilha G (DD-02) sobre a façade `dataipsum.api`/`dataipsum.config`. Até lá, os
sinks em si (`dataipsum.sinks`) já são testáveis diretamente:

```bash
uv run python -c "
import pyarrow as pa
from dataipsum.contracts.sink import RunContext
from dataipsum.sinks.csv_sink import CsvSink
from dataipsum.schema.models import ColumnSpec, PrimaryKeySpec, TableSpec

schema = pa.schema([('id', pa.int64()), ('nome', pa.string())])
table = TableSpec(
    name='usuarios', rows=2,
    primary_key=PrimaryKeySpec(columns=['id'], strategy='sequence', start=1),
    columns=[ColumnSpec(name='id', type='int64'), ColumnSpec(name='nome', type='string')],
)
sink = CsvSink()
sink.open(RunContext(run_id='exemplo', out_dir='out/manual', seed=1), table, schema)
sink.write_chunk(1, pa.record_batch([pa.array([1, 2]), pa.array(['Ana', 'Bia'])], schema=schema))
print(open('out/manual/usuarios/part-00001.csv').read())
"
```
