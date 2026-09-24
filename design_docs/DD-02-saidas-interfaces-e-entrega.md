# DD-02 — Saídas, interfaces e entrega

| | |
|---|---|
| **Status** | Proposto (para revisão) |
| **Marcos** | M1 (sinks de arquivo, export DDL/Avro, CLI, Docker e contrato do schema) · M3 (Postgres, MySQL, Kafka e import de DDL) · M4 (apenas o contrato da API) |
| **Onda** | 1. Começa depois do merge do [DD-00](DD-00-fundacao-e-contratos.md), **em paralelo** com o [DD-01](DD-01-motor-de-geracao.md) |
| **Fonte** | `RESEARCH.md` §2.1 (CLI Typer), §2.2 (flags inline, contrato da UI), §2.3, §2.8, §2.9, §2.10, §3 (M1, M3, M4) |

---

## 0. Paralelização e integração

Este documento agrupa **quatro trilhas que são implementadas em paralelo**. Elas eram quatro design docs separados e foram agrupadas aqui por decisão de projeto. Cada trilha:

- depende **somente** dos contratos, registry, manifesto e fakes do DD-00;
- escreve **somente** nos próprios diretórios;
- tem design, guardrails, testes unitários, exemplos, critérios de aceitação e BDD próprios;
- corresponde a **um step** do `/task-creator`. O step 5 é a integração.

| Trilha | Escopo | Diretórios exclusivos | Step |
|---|---|---|---|
| **E** | Sinks e escrita idempotente | `src/dataipsum/sinks/`, `tests/sinks/`, `examples/sinks/`, `docker/fragments/sinks.*`, `tests/docker/test_image_sinks.py` | S1 |
| **F** | Import/export de schema | `src/dataipsum/schema_io/`, `tests/schema_io/`, `examples/schema-io/`, `docker/fragments/schema-io.*`, `tests/docker/test_image_schema_io.py` | S2 |
| **G** | CLI e compose de desenvolvimento | `src/dataipsum/cli/`, `docker-compose.yml`, `tests/cli/`, `examples/cli-docker/`, `docker/fragments/cli-docker.*`, `tests/docker/test_image_cli.py` | S3 |
| **H** | Contrato do schema e da API web (M4, só contrato) | `schemas/`, `docs/api/`, `examples/README.md`, `examples/loja.yaml`, `examples/contrato/`, `tests/contract/`, `docker/fragments/contrato.*`, `tests/docker/test_image_contrato.py` | S4 |
| — | Integração ponta a ponta | `tests/integration/e2e/` | S5 (depende de S1–S4 e do S5 do DD-01) |

**Regras de paralelismo:**
- S1, S2, S3 e S4 **começam juntos**, e também junto com as trilhas A–D do DD-01.
- **G** chama só a façade (`dataipsum.api`, DD-00 §3.8). Nos testes unitários, a façade é substituída por fakes, e G não espera o motor ficar pronto.
- **E** recebe `RecordBatch`es sintéticos nos testes e não depende do motor.
- **F** trabalha sobre o `Schema` e os `LogicalType`s do DD-00. Nos testes, usa geradores fake com `LogicalType`s declarados.
- **Única dependência cruzada interna** (M3): a parte **Kafka** da trilha E e a opção `create_tables` dos sinks de banco consomem funções da trilha F (`avro_schema(table)` e `ddl_for(schema, dialect)`). Para não travar:
  - F entrega essas duas funções **primeiro**, como a primeira sub-entrega do S2;
  - E desenvolve a parte M3 contra stubs com a mesma assinatura;
  - o encaixe acontece no S5.
- **Imagem Docker:** a imagem é criada no DD-00 (§3.12). Cada trilha a evolui **só pelo próprio fragmento** e pelos próprios testes de imagem, e tem a subseção "Evolução da imagem" (E.10, F.10, G.10, H.10). Nenhuma trilha edita o `Dockerfile`, que é gerado.
- O **S5** é o único step encadeado.

## 1. Contexto e escopo

Com o motor (DD-01) produzindo chunks, este documento cobre:
- **onde** os dados vão parar (sinks);
- **como** o schema entra e sai em outros formatos (DDL SQL, Avro);
- **como** o usuário opera o sistema (CLI e compose de desenvolvimento, sobre a imagem do DD-00);
- **qual contrato** a futura UI web usará.

## 2. Objetivos e não-objetivos (do documento)

**Objetivos**
- Sinks MVP: CSV, JSON/JSONL e Parquet. Depois, Postgres (COPY), MySQL e Kafka (Avro + Schema Registry), todos com **escrita idempotente por chunk**.
- Export de DDL por dialeto e de Avro Schema; `--emit-schema`; import de DDL (M3).
- CLI fina (Typer) e compose de dev com Ollama, usando a imagem criada no DD-00 §3.12. Cada trilha deste doc evolui a imagem pelo próprio fragmento.
- Contrato estável e versionado do schema para a UI (M4).

**Não-objetivos**
- Implementar a API FastAPI ou a UI React/React Flow. No M4, só o contrato (RESEARCH §2.10, decisão do usuário).
- Transações *exactly-once* no Kafka. Duplicatas em retry são aceitas porque a key = PK.
- Escrita em object storage (S3/GCS) direto pelo sink.
- Criar bancos ou tópicos em produção. `create_tables`/`create_topics` são opcionais e voltados a ambientes de teste.

---

## Trilha E — Sinks e escrita idempotente (S1)

### E.1 Contexto e escopo

A trilha E implementa a interface `Sink` (DD-00 §3.5):
- **M1:** `csv`, `json`, `jsonl` e `parquet`;
- **M3:** `postgres`, `mysql` e `kafka`.

A escrita acontece **no worker** (DD-01, D.3.2). Cada chunk é gravado de forma idempotente e pode ser **substituído** (chunks `pending_llm` com placeholder, no `resume`).

### E.2 Objetivos / Não-objetivos

- **Objetivo:** reprocessar um chunk, no mesmo ou em outro worker, nunca gera duplicata nem arquivo parcial visível.
- **Objetivo:** preservar os tipos lógicos (decimal exato, timestamps, uuid) em cada formato.
- **Não-objetivo:** particionamento Hive-style por coluna e compactação de arquivos pequenos.

### E.3 Design

#### E.3.1 Sinks de arquivo (M1)

- **Layout:** `<out>/<tabela>/part-<id>.<ext>`.
  - `<id>` é o `ChunkSpec.id` com zero-padding de 5 dígitos (`part-00001`), ampliado se houver ≥ 100.000 chunks.
- **Escrita atômica:**
  1. grava em `<out>/<tabela>/.part-<id>.<ext>.tmp-<uuid4>` no **mesmo diretório**;
  2. faz `fsync` do arquivo;
  3. faz `os.replace` para o nome final;
  4. faz `fsync` do diretório.
  - O sha256 é calculado durante a escrita e devolvido no `SinkReceipt`.
- `chunk_state(id)` é `committed` se o arquivo final existe.
- **Reescrever um chunk** repete o processo: o `os.replace` substitui atomicamente, e um leitor nunca vê arquivo parcial.
- **Limpeza:** ao abrir, o sink remove **apenas** arquivos que casam com `^\.part-\d+\.[a-z]+\.tmp-[0-9a-f-]{36}$` dentro de `<out>/<tabela>/`. Isso cobre temporários órfãos de uma execução interrompida.

| Formato | Detalhes |
|---|---|
| `parquet` | `pyarrow.parquet`; compressão `zstd` (padrão, configurável: `snappy`, `gzip`, `none`); tipos Arrow do `LogicalType` (decimal128, timestamp[ms], date32, time, string; uuid como string canônica); um row group por chunk |
| `csv` | UTF-8 sem BOM; cabeçalho em todo arquivo; RFC 4180 com aspas mínimas; `delimiter`: `,` (padrão), `;`, `\t` ou `\|`; `null_value` (padrão string vazia); booleanos `true`/`false`; decimal sem notação científica; datas ISO-8601; `json`/`array` como texto JSON; opção `escape_formulas` (padrão `false`) prefixa `'` em valores que começam com `=`, `+`, `-` ou `@` |
| `jsonl` | um objeto JSON por linha (**padrão** para "JSON"), com `ensure_ascii=False`; decimal como **string** (precisão exata); datas ISO-8601; uuid string; coluna `json` embutida como objeto; `array` como lista |
| `json` | um array JSON por arquivo, com as mesmas regras de valor do `jsonl` |

#### E.3.2 Sinks de banco (M3)

**Tabela de controle** `_dataipsum_chunks` (no schema de destino). Colunas:
- `run_id`, `table_name`, `chunk_id`;
- `status` (`committed` | `placeholder`), `rows`, `committed_at`;
- PK `(run_id, table_name, chunk_id)`.

**Escrita de um chunk em uma transação:**
1. `SELECT` na tabela de controle:
   - se `committed` e não é substituição ⇒ não faz nada (idempotência).
2. **Substituição** de chunk `placeholder`, que só existe quando o usuário escolheu `on_failure: placeholder`:
   - `UPDATE` **só das colunas LLM e das flags** (`is_offensive`, `is_placeholder`), linha a linha pela PK, em lotes;
   - as PKs são recalculadas deterministicamente com `pk_at` (DD-01, B.3.7). PK composta usa `WHERE a = %s AND b = %s`;
   - **não** se usa `DELETE` + reinserção: linhas filhas já gravadas referenciam essas PKs, e apagar violaria as FKs. As colunas determinísticas são idênticas por construção, então só o texto muda;
   - depois disso, pula para o passo 4.
3. Carga dos dados (chunk novo):
   - **Postgres:** `COPY <tabela> (<colunas>) FROM STDIN` via `psycopg` (`cursor.copy`), com identificadores montados por `psycopg.sql.Identifier`;
   - **MySQL:** `executemany` de `INSERT` em lotes de 1000 linhas via PyMySQL, com `autocommit=False`, InnoDB obrigatório e `local_infile` **desligado**.
4. `INSERT`/`UPDATE` na tabela de controle.
5. `COMMIT`. Em qualquer erro, `ROLLBACK`, e o chunk falha (retry do orquestrador).

**Ordem e FKs:**
- os sinks de banco declaram `capabilities.referential_integrity = true` (DD-00 §3.5);
- o agendamento por grafo (DD-01, D.3.1) só começa uma tabela depois das tabelas das quais ela depende;
- um chunk filho que referencia um chunk pai ainda não `done` (por exemplo `pending_llm`) **espera**: não é gravado e fica `pending` com `blocked_by` (DD-01, C.3.7). O `resume` grava o pai primeiro e depois os filhos;
- o motor **nunca** troca para placeholder por conta própria (decisão do usuário).

**Opções:**
- conexão:
  - `dsn_env` (nome da variável com a DSN); **ou**
  - `host`, `port`, `database`, `user` + `password_env`;
- `db_schema` (Postgres, padrão `public`);
- `sslmode` (padrão `prefer`; os exemplos usam `require`);
- `create_tables` (padrão `false`): executa o DDL de `ddl_for(schema, dialect)` da trilha F, com `CREATE TABLE IF NOT EXISTS`.

#### E.3.3 Sink Kafka (M3)

- **Um tópico por tabela:** `<topic_prefix><tabela>`, com `topic_prefix` padrão `<schema.name>.`.
- **Producer** `confluent-kafka` com:
  - `enable.idempotence=true`;
  - `acks=all`;
  - `compression.type=zstd`;
  - `linger.ms=20`.
- **Valor:** `AvroSerializer` com o schema de `avro_schema(table)` da trilha F. O subject usa `TopicNameStrategy` e `auto_register_schemas` é configurável (padrão `true`).
- **Key = PK:**
  - PK simples: string canônica;
  - PK composta: texto JSON `[a, b]`;
  - usa `StringSerializer`.
- **Um chunk está concluído** quando `flush()` retorna e **todos** os delivery reports vieram sem erro. Qualquer erro faz o chunk falhar, e o orquestrador tenta de novo.
  - Duplicatas por retry ou `resume` são aceitas: com key = PK, tópicos compactados e consumidores *upsert* convergem (não-objetivo *exactly-once*).
- `chunk_state` é sempre `absent`: o Kafka não guarda estado consultável, então vale o manifesto.
- **Opções:**
  - `bootstrap_servers`, `schema_registry_url`;
  - `security_protocol`, `sasl_mechanism`, `sasl_username_env`, `sasl_password_env`;
  - `schema_registry_basic_auth_env`;
  - `create_topics` (padrão `false`; usa AdminClient, com `partitions` e `replication_factor`).

### E.4 APIs

- `sinks.register(registry)` registra `csv`, `json`, `jsonl` e `parquet`. Também registra `postgres`, `mysql` e `kafka` **somente se** o extra correspondente estiver instalado; sem o extra, usar o formato gera um erro que indica `pip install dataipsum[<extra>]`.
- `SinkConfig` (picklable) → `Sink`, construído no worker.
- `capabilities`: arquivos e Kafka têm `referential_integrity = false`; Postgres e MySQL, `true`.

### E.5 Guardrails e validações

1. **Confinamento de caminho:**
   - todo arquivo passa pela verificação do DD-00, dentro de `<out>` e sem symlinks;
   - o nome do arquivo deriva só de identificadores validados e do ID numérico.
2. **Limpeza restrita** aos temporários que casam com o padrão exato: o sink nunca apaga outros arquivos.
3. **SQL:**
   - identificadores sempre quotados pelo driver (`psycopg.sql.Identifier`, crase escapada no MySQL) **e** validados pela regex do DD-00;
   - valores sempre por parâmetros ou COPY, **nunca** por concatenação;
   - `local_infile` desligado no MySQL.
4. **Credenciais:**
   - só por `*_env`;
   - as opções do sink passam pelo sanitizador do DD-00 antes de ir para o manifesto e os logs;
   - DSN nunca é logada.
5. **TLS:**
   - `sslmode` e `security_protocol` configuráveis;
   - aviso quando um host não local usa conexão sem TLS.
6. **Transações por chunk** e tabela de controle, que evitam duplicatas no banco.
7. **Erros fatais**, que param o job (DD-01, D.3.1): falha de autenticação, banco/tópico inexistente sem `create_*` e disco cheio.
8. `escape_formulas` disponível para CSVs que serão abertos em planilhas. É desligado por padrão para não alterar os dados.

### E.6 Testes unitários (obrigatórios, em `tests/sinks/unit/`)

| Alvo | Testes mínimos |
|---|---|
| layout/atomicidade | nome `part-00001`; padding > 99.999; falha simulada antes do `os.replace` não deixa o arquivo final; reescrita substitui; sha256 no receipt; limpeza remove só temporários do padrão exato (arquivos "parecidos" ficam) |
| `parquet` | round-trip de cada `LogicalType` (decimal exato, timestamp ms, date, time, uuid, json, array, nulos); compressões |
| `csv` | cabeçalho; delimitadores; aspas e quebras de linha; `null_value`; `escape_formulas`; decimal sem notação científica |
| `jsonl`/`json` | um objeto por linha; decimal como string; `json` embutido como objeto; UTF-8 sem escape |
| confinamento | tabela com nome inválido nunca chega ao sink (validação); symlink em `<out>/<tabela>` gera `OutputDirError` |
| Postgres/MySQL (com conexão fake/mock) | sequência de transação (SELECT de controle → COPY/INSERT → controle → COMMIT); substituição de `placeholder` usa `UPDATE` das colunas LLM e flags por PK, **nunca** `DELETE`, e não viola as FKs de filhos já gravados; `capabilities.referential_integrity = true`; idempotência (chunk `committed` não é regravado); substituição de `placeholder`; ROLLBACK em erro; identificadores quotados; `local_infile` desligado; DSN ausente dos logs |
| Kafka (com producer/serializer mock) | key = PK (simples e composta); config idempotente; chunk só `done` após todos os delivery reports; erro em um report faz o chunk falhar; tópico `<prefix><tabela>` |
| registro condicional | sem extra, o formato gera erro com instrução de instalação |

Testes `integration` em `tests/sinks/integration/`, com testcontainers para Postgres, MySQL e Kafka + Schema Registry, cobrem a carga real, a idempotência sob retry e a substituição.

### E.7 Exemplos de features opcionais (em `examples/sinks/`)

| Arquivo | Demonstra |
|---|---|
| `csv-opcoes.sh` | `--format csv` com `delimiter=;`, `null_value=NULL`, `escape_formulas=true` |
| `jsonl-e-json.sh` | diferença entre `jsonl` e `json` |
| `parquet-compressao.sh` | `compression=snappy` × `zstd` |
| `postgres/` | compose com Postgres + `dataipsum gen --format postgres --sink-opt dsn_env=PG_DSN --sink-opt create_tables=true` (extra `[postgres]`) |
| `mysql/` | idem com MySQL (extra `[mysql]`) |
| `kafka/` | compose com Kafka + Schema Registry, `--format kafka` e um consumidor Avro de verificação (extra `[kafka]`) |
| `README.md` | pré-requisitos, comandos e saída esperada |

### E.8 Critérios de aceitação

- **E-01** Cada tabela gera `part-XXXXX.<ext>` por chunk, e nenhum arquivo `.tmp-` resta após uma execução completa.
- **E-02** Matar o processo durante a escrita e rodar `resume` não deixa arquivo corrompido nem duplicado.
- **E-03** Os valores de decimal, timestamp, date, time e uuid fazem round-trip exato em Parquet e JSONL.
- **E-04 (M3)** Postgres/MySQL: reexecutar o mesmo chunk não duplica linhas; `COUNT(*)` bate com o plano.
- **E-05 (M3)** Substituir um chunk `placeholder` atualiza só o texto LLM e as flags. A contagem não muda, as FKs de filhos já gravados continuam válidas e `is_placeholder` fica `false`.
- **E-09 (M3)** Com o provedor LLM fora do ar no pai e `on_failure: pending`, nenhum filho órfão é inserido no banco: os chunks filhos afetados ficam `pending` com `blocked_by` até o `resume`.
- **E-06 (M3)** Kafka: cada mensagem tem key = PK e valor Avro registrado no Schema Registry, desserializável pelo `.avsc` da trilha F.
- **E-07** Nenhuma senha ou DSN aparece no manifesto ou nos logs.
- **E-08** Os testes de E.6 existem e passam. Os exemplos de E.7 existem e têm README.

### E.9 BDD

```gherkin
# language: pt
Funcionalidade: Sinks com escrita idempotente

  Cenário: Arquivo por chunk com rename atômico
    Dado a tabela "usuarios" com 25000 linhas e chunk_size 10000
    Quando eu gero com --format parquet
    Então existem os arquivos "usuarios/part-00001.parquet" a "usuarios/part-00003.parquet"
    E nenhum arquivo temporário permanece em "usuarios/"

  Cenário: Falha no meio da escrita
    Dado uma falha simulada antes do rename do chunk 2
    Quando a execução termina
    Então "part-00002.parquet" não existe
    E o manifesto marca o chunk 2 como não concluído
    Quando eu executo resume
    Então "part-00002.parquet" existe e é válido

  Cenário: Idempotência no Postgres (M3)
    Dado um banco Postgres com a tabela de controle
    Quando o chunk 1 de "usuarios" é escrito duas vezes
    Então "usuarios" contém exatamente as linhas do chunk 1 uma única vez

  Cenário: Kafka com chave igual à PK (M3)
    Dado um tópico "loja.usuarios" e um Schema Registry
    Quando eu gero "usuarios" com --format kafka
    Então cada mensagem tem key igual ao "id" do usuário
    E o valor é Avro compatível com "usuarios.avsc"
```

### E.10 Evolução da imagem

- **Fragmento:** nenhum pacote de SO. `psycopg[binary]`, PyMySQL (Python puro) e `confluent-kafka` (wheel com librdkafka) não exigem compilador nem bibliotecas do sistema. Se uma versão futura exigir, a mudança entra em `docker/fragments/sinks.runtime.dockerfile`, e nunca como compilador no estágio final.
- **Testes** (`tests/docker/test_image_sinks.py`):
  - a imagem com `EXTRAS=postgres,mysql,kafka` constrói sem compilador;
  - `import psycopg, pymysql, confluent_kafka` funciona dentro do container;
  - com `--network none`, `gen --format parquet` grava em `/out` como UID 10001;
  - com testcontainers (marker `integration`), `--format postgres` a partir do container carrega os dados.
- **Critério E-10:** os testes acima passam.

---

## Trilha F — Import e export de schema (S2)

### F.1 Contexto e escopo

A trilha F cobre:
- **export de DDL** SQL por dialeto;
- **export de Avro Schema** (`.avsc` por tabela);
- `--emit-schema` durante a geração;
- **import de DDL** (M3), que converte `CREATE TABLE` em schema dataIpsum.

A trilha usa `sqlglot`, que já está na base desde o M1.

### F.2 Objetivos / Não-objetivos

- **Objetivo:** o DDL exportado executa sem erro em Postgres e MySQL e aceita os dados gerados.
- **Objetivo:** o Avro é reutilizado sem alterações pelo sink Kafka.
- **Não-objetivo:** exportar índices, triggers, views ou comentários.
- **Não-objetivo:** importar dados, `INSERT`s ou procedures. O import lê só a estrutura.

### F.3 Design

#### F.3.1 Export de DDL (`ddl_for(schema, dialect) -> str`)

- Monta expressões `sqlglot` (`exp.Create` etc.) e gera o SQL com `.sql(dialect=...)`. **Nunca** usa concatenação de strings com nomes.
- Todos os identificadores são quotados.
- **Dialetos testados:** `postgres` e `mysql`. Outros dialetos do sqlglot são aceitos com aviso de "não testado".
- **Ordem:** `CREATE TABLE` em ordem topológica. As FKs ficam inline (`REFERENCES pai(pk)`).
- **Restrições:**
  - PK (simples ou composta);
  - FK para cada `ref`;
  - `UNIQUE` na FK de `one_to_one`;
  - **`NOT NULL`** em toda coluna com `null_ratio = 0` e nas flags `is_offensive`/`is_placeholder`.
- **Mapeamento `LogicalType` → SQL:**

| LogicalType | Postgres | MySQL |
|---|---|---|
| `string(N)` | `VARCHAR(N)` (N **declarado pelo usuário**, decisão do usuário) | `VARCHAR(N)` |
| `text` (LLM sem `max_length`) | `TEXT` | `TEXT` |
| `char(n)` (CPF/RG, conforme `format`) | `CHAR(n)` | `CHAR(n)` |
| `int32` / `int64` | `INTEGER` / `BIGINT` | `INT` / `BIGINT` |
| `float64` | `DOUBLE PRECISION` | `DOUBLE` |
| `decimal(p,s)` | `DECIMAL(p,s)` | `DECIMAL(p,s)` |
| `boolean` | `BOOLEAN` | `BOOLEAN` |
| `date` | `DATE` | `DATE` |
| `time` (s / ms) | `TIME` / `TIME(3)` | `TIME` / `TIME(3)` |
| `timestamp(tz=false)` | `TIMESTAMP(3)` | `DATETIME(3)` |
| `timestamp(tz=true)` | `TIMESTAMPTZ(3)` | `TIMESTAMP(3)` (armazenado em UTC) |
| `uuid` | `UUID` | `CHAR(36)` |
| `json` | `JSONB` | `JSON` |
| `array(item)` | `<item>[]` | `JSON` |

- **Tamanho dos textos:**
  - o comprimento de `VARCHAR` sempre vem do `max_length` declarado (decisão do usuário, que **substitui** a regra "maior valor gerado" do RESEARCH);
  - campos com regra têm comprimento fixo pela máscara (DD-01, A.3);
  - LLM sem N vira `TEXT`;
  - `email` (endereço, DD-01 A.3) é `string(max_length)`: `VARCHAR(N)` em SQL e `string` no Avro, com N = `max_length` (padrão 254). O `llm_email` (corpo, LLM) segue a regra dos `llm_*`.

#### F.3.2 Export de Avro (`avro_schema(table) -> dict`)

- Um `record` por tabela, com `name` = tabela e `namespace` = `dataipsum.<schema.name>`.

| LogicalType | Avro |
|---|---|
| `string(N)`, `text`, `char(n)` | `string` |
| `int32` / `int64` | `int` / `long` |
| `float64` | `double` |
| `decimal(p,s)` | `{"type":"bytes","logicalType":"decimal","precision":p,"scale":s}` |
| `boolean` | `boolean` |
| `date` | `{"type":"int","logicalType":"date"}` |
| `time` | `{"type":"int","logicalType":"time-millis"}` |
| `timestamp` | `{"type":"long","logicalType":"timestamp-millis"}` (sem tz é interpretado como UTC) |
| `uuid` | `{"type":"string","logicalType":"uuid"}` |
| `json` | `string` (texto JSON) |
| `array(item)` | `{"type":"array","items":<item>}` |

- **Anuláveis** (`null_ratio > 0`): union `["null", T]` com `"default": null`.
- FKs e PK são documentadas no atributo `doc` do campo (ex.: `"FK → usuarios.id"`). Isso é informativo: o Avro não modela restrições.

#### F.3.3 Comandos e `--emit-schema`

- **`dataipsum schema export SCHEMA --format ddl|avro [--dialect postgres] -o DIR`** grava:
  - DDL: `DIR/<dialect>.sql`;
  - Avro: `DIR/<tabela>.avsc`.
- **`dataipsum gen ... --emit-schema ddl,avro [--dialect postgres]`:**
  - o orquestrador (DD-01, D.3.1) chama `api.export_schema` para `<out>/_schema/ddl/` e `<out>/_schema/avro/`;
  - cada arquivo é registrado em `manifest.emitted_schemas` com `sha256`.
- A escrita dos arquivos é atômica e confinada ao diretório de destino.

#### F.3.4 Import de DDL (M3)

- **Comando:** `dataipsum schema import FILE.sql --dialect postgres|mysql|... -o schema.yaml`.
- **Parse:**
  - `sqlglot.parse(sql, read=dialect)`;
  - considera **apenas** `CREATE TABLE` e `ALTER TABLE ... ADD [CONSTRAINT] PRIMARY KEY/FOREIGN KEY`;
  - demais comandos são ignorados, com aviso listando tipo e linha;
  - **o SQL nunca é executado**, e nenhuma conexão é aberta.
- **Tipos SQL → dataIpsum:**
  - `VARCHAR(n)` → `string` com `max_length: n`;
  - `VARCHAR`/`TEXT` sem n → `string`, `max_length: 255`, com TODO;
  - `CHAR(n)` → `char`;
  - `SMALLINT`/`INT`/`INTEGER`/`BIGINT` → `int`, com a faixa do tipo;
  - `SERIAL`/`BIGSERIAL`/`IDENTITY`/`AUTO_INCREMENT` → `int` + PK `sequence`;
  - `REAL`/`FLOAT`/`DOUBLE` → `float`;
  - `DECIMAL`/`NUMERIC(p,s)` → `decimal`;
  - `BOOLEAN`/`TINYINT(1)` → `boolean`;
  - `DATE`, `TIME`, `TIMESTAMP` → `date`, `time`, `timestamp`;
  - `TIMESTAMPTZ` → `timestamp` com `timezone: true`;
  - `UUID` → `uuid`;
  - `JSON`/`JSONB` → `json` com um campo `valor` de exemplo, com TODO;
  - `ARRAY` → `array`;
  - desconhecido → `string` 255, com aviso.
- **Nulos:** `NOT NULL` → `null_ratio: 0`. Colunas anuláveis também recebem 0 (padrão do RESEARCH), com nota no relatório.
- **Inferência por nome** (só em colunas textuais; o usuário ajusta depois):

| Padrão de nome (normalizado, minúsculas) | Tipo inferido |
|---|---|
| `cpf`, `*_cpf`, `cpf_*` | `cpf` (`unmasked` se o comprimento declarado for 11, senão `masked`) |
| `rg`, `*_rg`, `rg_*` | `rg` |
| contém `cartao`, `credit_card`, `card_number` | `cartao_credito` |
| `nome`, `nome_completo`, `name`, `full_name`, `*_nome` | `nome_proprio` (`first_name`/`primeiro_nome` → `parts: first`) |
| `email`, `e_mail`, `*_email` | `email` (**endereço**, decisão do usuário), com `max_length` do `VARCHAR(n)` limitado a 254. Se a tabela tiver uma coluna inferida como `nome_proprio`, ela é usada como `name_column`. O corpo de e-mail (`llm_email`) nunca é inferido pelo nome; o usuário escolhe explicitamente |
| `post`, `*_post` | `llm_post` |
| contém `contrato`, `contract` | `llm_contrato` |

- **Chaves e relações:**
  - **PK inteira** → `sequence`. **PK `UUID`** → `seeded_uuid`.
  - **PK textual** → erro com sugestão, porque não há estratégia de PK textual.
  - **PK composta formada por 2 FKs** → tabela `many_to_many`, com `via` = a 1ª FK, `pair` = a 2ª e `cardinality: {range: {min: 1, max: 3}}`.
  - **Outra PK composta** → erro.
  - **Tabela sem FK** → raiz, com `rows: 1000`.
  - **Tabela com FK:**
    - a **1ª FK** declarada vira `via`: `one_to_many` com `cardinality: {range: {min: 0, max: 5}}`, ou `one_to_one` com `coverage: 1.0` se a FK for `UNIQUE`;
    - as demais FKs viram `ref` não dirigente, `uniform`.
  - **Auto-FK** → convertida para coluna simples do mesmo tipo, com aviso (auto-relacionamento é não-objetivo).
  - **Ciclo** → erro com o caminho do ciclo.
- **Saída:**
  - YAML válido (passa por `dataipsum.validate`) que começa com um **bloco de comentários** "Revise:";
  - o bloco lista cada inferência, cada TODO e cada padrão aplicado;
  - o mesmo relatório vai para o stderr.

### F.4 APIs

- `ddl_for(schema, dialect) -> str`: **sub-entrega prioritária** do S2, consumida pela trilha E (`create_tables`).
- `avro_schema(schema, table) -> dict`: **sub-entrega prioritária** do S2, consumida pela trilha E (Kafka).
- `export_schema(schema, format, dialect, out_dir) -> list[Path]`: implementação da façade.
- `import_ddl(sql_text, dialect) -> (Schema, Report)`: implementação da façade (M3).

### F.5 Guardrails e validações

1. **O import nunca executa SQL** e não abre conexões. Os testes verificam que nenhum módulo de driver é importado pelo import.
2. **Limites do import:**
   - arquivo ≤ 5 MiB;
   - ≤ 200 tabelas;
   - ≤ 500 colunas por tabela;
   - identificadores do DDL que não casam com a regex do DD-00 são **normalizados** (minúsculas, caracteres inválidos → `_`, prefixo `_` se começar com dígito, truncados em 63 caracteres) e listados no relatório;
   - uma colisão após a normalização é erro.
3. **Export:**
   - identificadores quotados via sqlglot;
   - nenhum dado do usuário além de nomes validados entra no DDL;
   - arquivos gravados atomicamente dentro do diretório de destino.
4. O YAML emitido pelo import passa pela validação completa antes de ser gravado. Se não passar, o comando falha e mostra os erros.
5. O Avro gerado é validado com `fastavro.parse_schema` nos testes (dependência de dev).

### F.6 Testes unitários (obrigatórios, em `tests/schema_io/unit/`)

| Alvo | Testes mínimos |
|---|---|
| DDL | cada linha da tabela de mapeamento em Postgres e MySQL; `NOT NULL` ↔ `null_ratio = 0`; `VARCHAR(N)` = `max_length`; `TEXT` para LLM sem N; `CHAR(14)`/`CHAR(11)` do CPF; PK composta; FK inline; `UNIQUE` em 1:1; ordem topológica; identificadores quotados (tabela `order`, `user`); o DDL re-parseia com sqlglot no mesmo dialeto; dialeto não testado emite aviso |
| Avro | cada linha da tabela de mapeamento; union `["null", T]` com default null; `namespace`; `doc` de FK; `fastavro.parse_schema` aceita todos |
| emit | `--emit-schema ddl,avro` grava em `<out>/_schema/` e registra os sha256 no manifesto (com manifesto em memória) |
| import: parse | apenas CREATE/ALTER considerados; outros ignorados com aviso; SQL > 5 MiB rejeitado; nenhum driver importado |
| import: tipos | cada linha do mapeamento SQL → dataIpsum; desconhecido → string + aviso |
| import: nomes | cada padrão da tabela de inferência; colunas não textuais nunca inferidas; `email VARCHAR(120)` → `email` (endereço) com `max_length: 120` e `name_column` quando há coluna de nome; nada é inferido como `llm_email` |
| import: chaves | serial/identity → `sequence`; uuid → `seeded_uuid`; PK textual → erro; ponte com 2 FKs → `many_to_many`; FK `UNIQUE` → `one_to_one`; auto-FK → coluna simples + aviso; ciclo → erro |
| import: saída | YAML válido; bloco "Revise:"; normalização de identificadores e colisão |
| round-trip | schema → DDL → import → schema equivalente (tipos, PK e FK) nos exemplos de referência |

Testes `integration` executam o DDL em Postgres e MySQL reais (testcontainers) e carregam os dados gerados.

### F.7 Exemplos de features opcionais (em `examples/schema-io/`)

| Arquivo | Demonstra |
|---|---|
| `export-ddl-postgres.sh` | `schema export --format ddl --dialect postgres` |
| `export-ddl-mysql.sh` | o mesmo em MySQL |
| `export-avro.sh` | `schema export --format avro` |
| `emit-schema.sh` | `gen ... --emit-schema ddl,avro` e as entradas no manifesto |
| `import/loja.sql` + `import.sh` | import de DDL com PK, FK, ponte, `email`, `cpf` e o relatório "Revise:" |
| `README.md` | comandos e saída esperada |

### F.8 Critérios de aceitação

- **F-01** O DDL exportado de `examples/loja.yaml` executa sem erro em Postgres 16 e MySQL 8, e os dados gerados carregam sem violar restrições (integration).
- **F-02** `NOT NULL` aparece exatamente nas colunas com `null_ratio = 0` e nas flags.
- **F-03** Os comprimentos de `VARCHAR(N)` são iguais aos `max_length` declarados.
- **F-04** Cada `.avsc` passa em `fastavro.parse_schema` e usa os logical types `date`, `timestamp-millis`, `uuid` e `decimal` onde aplicável. Os campos anuláveis são `["null", T]`.
- **F-05** Com `--emit-schema`, os arquivos existem em `<out>/_schema/` e estão no manifesto com sha256 corretos.
- **F-06 (M3)** O import de `examples/schema-io/import/loja.sql` gera YAML válido, com as inferências esperadas e sem executar SQL.
- **F-07** Os testes de F.6 existem e passam. Os exemplos de F.7 existem e têm README.

### F.9 BDD

```gherkin
# language: pt
Funcionalidade: Import e export de schema

  Cenário: Export de DDL para Postgres
    Dado o schema "examples/loja.yaml"
    Quando eu executo "dataipsum schema export examples/loja.yaml --format ddl --dialect postgres -o ddl/"
    Então "ddl/postgres.sql" contém "CREATE TABLE" para cada tabela em ordem topológica
    E a coluna "bio" com max_length 200 e null_ratio 0.1 é "VARCHAR(200)" sem "NOT NULL"
    E a coluna "cpf" é "CHAR(14) NOT NULL"
    E "pedidos.usuario_id" tem "REFERENCES" para "usuarios"

  Cenário: Export de Avro
    Quando eu exporto o schema em formato avro
    Então existe um ".avsc" por tabela
    E "criado_em" tem logicalType "timestamp-millis"
    E "bio" é a union ["null", "string"]

  Cenário: Emitir schema junto com a geração
    Quando eu executo "dataipsum gen examples/loja.yaml -o out --emit-schema ddl,avro"
    Então o manifesto lista os arquivos de "out/_schema/" com sha256

  Cenário: Import de DDL com inferência (M3)
    Dado um arquivo SQL com "CREATE TABLE clientes (id SERIAL PRIMARY KEY, cpf CHAR(11) NOT NULL, email VARCHAR(120))"
    Quando eu executo "dataipsum schema import clientes.sql --dialect postgres -o clientes.yaml"
    Então "clientes.yaml" é válido
    E "cpf" tem type "cpf" e format "unmasked"
    E "email" tem type "email" e max_length 120
    E o arquivo começa com um bloco de comentários "Revise:"
    E nenhuma conexão de banco foi aberta
```

### F.10 Evolução da imagem

- **Fragmento:** nenhum (`sqlglot` já está na base).
- **Testes** (`tests/docker/test_image_schema_io.py`): dentro do container, `schema export --format ddl --dialect postgres` e `--format avro` gravam em `/out` com `--network none`. `schema import` de um `.sql` montado em `/schemas` gera YAML válido.
- **Critério F-08:** os testes acima passam.

---

## Trilha G — CLI e compose de desenvolvimento (S3)

### G.1 Contexto e escopo

A trilha G cobre:
- a CLI fina em Typer sobre a façade;
- o compose de dev com Ollama, que usa a imagem criada no DD-00 (§3.12). A imagem base, o `.dockerignore` e o mecanismo de fragmentos **não** são desta trilha, que substitui os scripts elvish de `study/`. Esses scripts **não existem** no repositório, e a remoção já foi confirmada no DD-00.

### G.2 Objetivos / Não-objetivos

- **Objetivo:** toda funcionalidade é acessível por CLI **sem lógica de negócio na CLI**, que só faz parsing, chama a façade e formata a saída.
- **Objetivo:** o compose de dev sobe dataipsum + Ollama com a mesma imagem única do DD-00, com endurecimento de runtime (read-only, sem capabilities).
- **Não-objetivo:** publicar a imagem num registry (CI/CD de release).
- **Não-objetivo:** orquestrar clusters Ray em produção. O exemplo de cluster local fica no DD-01, D.7.

### G.3 Design

#### G.3.1 Comandos

| Comando | Função |
|---|---|
| `dataipsum gen [SCHEMA] -o OUT [opções]` | gera os dados. `SCHEMA` é YAML/JSON **ou** as flags inline |
| `dataipsum resume OUT [--llm-only]` | retoma pelo manifesto |
| `dataipsum schema validate SCHEMA` | valida e lista os erros com caminho |
| `dataipsum schema export SCHEMA --format ddl\|avro [--dialect D] -o DIR` | trilha F |
| `dataipsum schema import FILE.sql --dialect D -o schema.yaml` | trilha F (M3) |
| `dataipsum schema jsonschema [-o FILE]` | imprime o JSON Schema do formato (trilha H) |
| `dataipsum --version` | versão |

**Opções de `gen`:**
- `--seed N`, `--chunk-size N`, `--max-rows N`;
- `--format csv|json|jsonl|parquet|postgres|mysql|kafka` (padrão `parquet`) e `--sink-opt chave=valor` (repetível);
- `--executor local|ray`, `--ray-address`;
- `--cpu-max`, `--mem-max`;
- `--emit-schema ddl,avro`, `--dialect`;
- `--llm-on-failure pending|placeholder`, `--no-cache`, `--cache-dir`;
- `--no-plugins`;
- `--json`: resumo final em JSON no stdout;
- `-v`/`-q`.

**Flags inline** (RESEARCH §2.2), para casos rápidos de **uma tabela**:
- `dataipsum gen --table users --rows 100 --col id:int:pk --col nome:nome_proprio --col bio:string:max_length=50 -o out`;
- gramática `nome:tipo[:pk][:chave=valor]...`;
- o parsing é da CLI, e a montagem do schema usa `build_inline_schema` (DD-00);
- `--print-schema` imprime o YAML equivalente e sai;
- relações exigem YAML, e o erro explica isso.

**Saída e códigos:**
- progresso e logs vão para o **stderr**; o stdout fica limpo, com `--json` para máquinas;
- códigos de saída:

| Código | Significado |
|---|---|
| `0` | sucesso: execução `completed`, validação sem erros, export/import concluídos |
| `1` | qualquer erro: schema inválido, uso incorreto, execução `partial` (pendências), falha de execução ou interrupção (Ctrl+C) |

- Por decisão do usuário, **só existem 0 e 1 por enquanto**. O tipo de erro vai na mensagem do stderr e, com `--json`, no campo `status`/`error`.
- O Typer/Click devolve 2 em erro de uso por padrão. A CLI intercepta isso (modo não standalone) e converte para 1.

- **Ctrl+C:** o driver para de submeter, espera os chunks em voo por até 10 s, grava o manifesto (`partial`) e sugere `dataipsum resume`.

#### G.3.2 `docker-compose.yml` (dev)

- **`ollama`:**
  - imagem `ollama/ollama` com tag fixa;
  - volume nomeado `ollama-models`;
  - **sem `ports` publicados**: só acessível na rede interna do compose;
  - healthcheck `ollama list`.
- **`ollama-pull`** (one-shot): baixa `${DATAIPSUM_LLM_MODEL:-llama3.1:8b}` e sai.
- **`dataipsum`:**
  - `build` com `EXTRAS` via `${EXTRAS:-}`;
  - `DATAIPSUM_LLM_PROVIDER=ollama` e `DATAIPSUM_LLM_BASE_URL=http://ollama:11434`;
  - volumes `./examples:/schemas:ro` e `./out:/out`;
  - `user: "10001:10001"`;
  - `read_only: true` com `tmpfs: /tmp`;
  - volume nomeado `dataipsum-models` em `/var/cache/dataipsum/models`, a única pasta gravável fora de `/out` e `/tmp`, para os pesos de toxicidade;
  - `cap_drop: [ALL]`;
  - `security_opt: [no-new-privileges:true]`;
  - `depends_on`: `ollama` saudável + `ollama-pull` concluído.
- **Profile `gpu`:** reserva a GPU NVIDIA para o `ollama`.

### G.4 APIs

- `dataipsum.cli:app` (Typer).
- A CLI **só** importa `dataipsum.api` e `dataipsum.config`. Um teste de arquitetura garante que ela não importa `types/`, `relations/`, `llm/`, `execution/`, `sinks/` nem `schema_io/` diretamente.

### G.5 Guardrails e validações

1. **Segredos:**
   - a CLI não aceita segredos como argumento (`--password`, `--api-key` não existem), porque argumentos aparecem em `ps` e no histórico;
   - `--sink-opt` com chave que casa com `(?i)pass|secret|token|key` é **rejeitada**, com instrução para usar `*_env`. **Exceção:** chaves terminadas em `_env` (`password_env`, `dsn_env`, `sasl_password_env`...) são aceitas, porque carregam só o nome da variável (mesma regra do sanitizador do DD-00 §6.5).
2. **Caminhos:** `-o` é resolvido e validado pela façade (DD-00 §6); a CLI não cria diretórios fora dele.
3. **Compose:**
   - `user: 10001`, `no-new-privileges`, `cap_drop ALL` e rootfs `read_only`;
   - a imagem Ollama tem tag fixa;
   - os guardrails da imagem em si estão no DD-00 §6, item 12.
4. **Rede:** o compose não publica a porta do Ollama no host.
5. **Validação primeiro:** `gen` valida o schema e os limites **antes** de criar qualquer arquivo em `-o`.
6. **Saída:** mensagens de erro sem stack trace por padrão (`-v` mostra) e sem valores de segredos.

### G.6 Testes unitários (obrigatórios, em `tests/cli/unit/`, com `typer.testing.CliRunner` e façade fake)

| Alvo | Testes mínimos |
|---|---|
| `gen` | cada opção chega em `RunOptions` com o valor certo; precedência CLI > env; `--format` desconhecido → código 1; schema inválido → código 1 com os caminhos dos erros; `partial` → 1; falha → 1; sucesso → 0; erro de uso do Click (2) convertido para 1 |
| inline | a gramática `nome:tipo[:pk][:k=v]` (válida e inválida); `--print-schema` gera YAML equivalente e válido; relações inline → erro explicativo |
| `resume` | chama `api.resume`; `--llm-only` |
| `schema *` | `validate`, `export`, `import` e `jsonschema` chamam as funções certas da façade e gravam no caminho indicado |
| segredos | `--sink-opt password=x` rejeitado; `password_env=X` aceito; segredos nunca impressos |
| saída | stdout limpo sem `--json`; `--json` é JSON válido; logs no stderr |
| Ctrl+C | `KeyboardInterrupt` simulado → código 1, manifesto `partial` e sugestão de `resume` |
| arquitetura | a CLI não importa os pacotes de trilha diretamente |
| compose (marcados `docker`) | `docker compose config` válido; `ollama` sem `ports`; `dataipsum` com `read_only`, `cap_drop`, `no-new-privileges`; o serviço `dataipsum` usa o `Dockerfile` gerado do DD-00; o volume `dataipsum-models` fica montado em `/var/cache/dataipsum/models` e é gravável com rootfs `read_only` |

### G.7 Exemplos de features opcionais (em `examples/cli-docker/`)

| Arquivo | Demonstra |
|---|---|
| `inline.sh` | geração com flags inline e `--print-schema` |
| `formatos.sh` | `--format csv/jsonl/parquet` com `--sink-opt` |
| `json-saida.sh` | `--json` para automação |
| `compose-ollama.md` | `docker compose up`, `docker compose run dataipsum gen /schemas/llm/ollama-local.yaml -o /out`, profile `gpu` |
| `README.md` | explicação e saída esperada |

### G.8 Critérios de aceitação

- **G-01** Todos os comandos da G.3.1 existem, e `--help` de cada um documenta as opções.
- **G-02** `dataipsum gen --table users --rows 10 --col id:int:pk --col nome:nome_proprio -o out --format csv` gera 10 linhas com cabeçalho `id,nome` (após o S5 do DD-01).
- **G-03** A CLI só retorna 0 (sucesso) ou 1 (qualquer erro, inclusive uso incorreto, `partial` e Ctrl+C).
- **G-04** A imagem do DD-00, com a CLI completa desta trilha, responde a todos os comandos da G.3.1 dentro do container (G.10).
- **G-05** O `docker compose up` de dev sobe o Ollama saudável, sem porta publicada no host, e o `dataipsum` consegue gerar `examples/llm/ollama-local.yaml` (smoke manual/marcado).
- **G-06** Os testes de G.6 existem e passam. Os exemplos de G.7 existem e têm README.

### G.9 BDD

```gherkin
# language: pt
Funcionalidade: CLI e compose de desenvolvimento

  Cenário: Geração rápida com flags inline
    Quando eu executo "dataipsum gen --table users --rows 10 --col id:int:pk --col nome:nome_proprio -o out --format csv"
    Então o código de saída é 0
    E "out/users/part-00001.csv" tem 10 linhas de dados e cabeçalho "id,nome"

  Cenário: Schema inválido
    Dado um schema com a coluna "cpf" com invalid_ratio 2
    Quando eu executo "dataipsum schema validate schema.yaml"
    Então o código de saída é 1
    E a saída de erro contém "tables[0].columns[0].invalid_ratio"

  Cenário: Segredo como argumento é recusado
    Quando eu executo "dataipsum gen s.yaml -o out --format postgres --sink-opt password=123"
    Então o código de saída é 1
    E a mensagem sugere "password_env"
    E a saída não contém "123"

  Cenário: Nome de variável de ambiente é aceito
    Quando eu executo "dataipsum gen s.yaml -o out --format postgres --sink-opt password_env=PG_PASS"
    Então a opção é aceita
    E o manifesto registra "password_env": "PG_PASS" sem o valor da variável

  Cenário: Execução parcial retorna erro
    Dado um provedor LLM indisponível
    Quando eu executo "dataipsum gen examples/llm/ollama-local.yaml -o out"
    Então o código de saída é 1
    E a saída de erro sugere "dataipsum resume out"

  Cenário: CLI completa dentro da imagem
    Dado a imagem gerada pelo Dockerfile do DD-00 com a CLI desta trilha
    Quando eu executo "docker run --network none <imagem> schema validate /schemas/loja.yaml" com "examples" montado em "/schemas"
    Então o código de saída é 0
```

### G.10 Evolução da imagem

- **Fragmento:** nenhum. A CLI completa substitui o esqueleto do DD-00 S1 **sem mudar** o `ENTRYPOINT ["dataipsum"]`.
- **Compose de dev:** usa o `Dockerfile` gerado do DD-00. Os valores de runtime (provedor Ollama, volume de modelos) vêm do compose, e não da imagem.
- **Testes** (`tests/docker/test_image_cli.py`):
  - cada comando da G.3.1 responde `--help` dentro do container;
  - códigos de saída 0/1 são preservados através do `docker run`;
  - Ctrl+C (`docker stop`) grava o manifesto `partial`.
- **Critério G-07:** os testes acima passam.

---

## Trilha H — Contrato do schema e da API web (S4; M4 só contrato)

### H.1 Contexto e escopo

O RESEARCH §2.10 põe a UI **fora do MVP**. A única garantia é o **contrato**: o schema YAML/JSON e uma API futura em FastAPI (decisão do usuário: M4 só contrato).

A trilha H entrega:
- o **JSON Schema versionado** do formato;
- as **regras de compatibilidade**;
- o **esboço da API**, como documento OpenAPI de rascunho;
- o **índice de exemplos** e o teste que valida todos os exemplos do repositório.

### H.2 Objetivos / Não-objetivos

- **Objetivo:** a UI futura salva e carrega **exatamente** o mesmo schema que a CLI usa.
- **Objetivo:** o JSON Schema publicado nunca diverge do modelo Pydantic (teste de drift).
- **Não-objetivo:** implementar FastAPI, autenticação, React ou React Flow. O stack sugerido (React + React Flow, canvas estilo Miro/draw.io) fica só registrado.

### H.3 Design

#### H.3.1 JSON Schema versionado

- `schemas/dataipsum-schema.v1.json`, gerado por `dataipsum schema jsonschema` (DD-00 §3.3) e versionado no git.
- **Teste de drift:** gera de novo e compara byte a byte com o arquivo versionado. Uma diferença falha o teste, e o PR precisa atualizar o arquivo **e** justificar a mudança pelas regras de H.3.2.
- `$id`: `https://dataipsum.local/schemas/dataipsum-schema.v1.json`. É identificador, não URL resolvível.

#### H.3.2 Regras de compatibilidade

- **Mudança aditiva** (campo opcional novo com padrão que preserva o comportamento) ⇒ mesma `version: 1`.
- **Mudança incompatível** (remover ou renomear campo, mudar semântica ou padrão) ⇒ `version: 2`, com um novo arquivo `…v2.json`. O loader mantém suporte a v1 por pelo menos um marco, com um conversor v1 → v2.
- A UI deve **preservar campos desconhecidos** ao salvar, o que permite o round-trip entre versões menores. Isso fica documentado para o M4.

#### H.3.3 Esboço da API (M4, não implementado)

`docs/api/openapi.v1.yaml` (rascunho) e `docs/api/README.md` descrevem:

| Método e rota | Função | Mapeia para |
|---|---|---|
| `POST /v1/schemas:validate` | valida um schema (corpo JSON) | `api.validate` |
| `POST /v1/plans` | calcula o plano (linhas por tabela, chunks) | `api.plan` |
| `POST /v1/runs` | inicia uma execução assíncrona | `api.generate` |
| `GET /v1/runs/{run_id}` | status e manifesto resumido | manifesto |
| `POST /v1/runs/{run_id}:resume` | retoma | `api.resume` |
| `POST /v1/schemas:export` | DDL/Avro | `api.export_schema` |
| `POST /v1/schemas:import` | DDL → schema (M3) | `api.import_ddl` |

**Requisitos de segurança** registrados para o M4:
- autenticação obrigatória;
- o cliente **nunca** informa caminhos de sistema de arquivos: o servidor escolhe o destino por `run_id`;
- limites de tamanho de corpo, de linhas e de execuções simultâneas por usuário;
- segredos do LLM e dos sinks só no servidor (env), nunca no corpo;
- CORS restrito.

#### H.3.4 Exemplos de referência e índice

- `examples/loja.yaml`: o schema completo do DD-00 §3.3. É a referência usada em testes de várias trilhas e no S5.
- `examples/README.md`: índice de todas as subpastas `examples/<área>/`, com o extra necessário de cada exemplo.
- `tests/contract/test_examples.py`:
  - valida **todo** `examples/**/*.yaml` com `dataipsum.validate` **e** com o JSON Schema publicado;
  - roda com `FakeSink` e `FakeLLM` os que não exigem extra;
  - pula, com o motivo, os que exigem extra ausente (DD-00 §3.2).

### H.4 Guardrails e validações

1. Teste de drift do JSON Schema: o contrato não muda sem um PR explícito.
2. Os exemplos são validados em CI: nenhum exemplo quebrado.
3. O esboço da API documenta os requisitos de segurança (H.3.3) como **obrigatórios** para o M4.
4. Os exemplos não contêm segredos: um teste varre `examples/` procurando padrões de chave (`sk-`, `AKIA`, `password:`) e valores literais em `*_env`.

### H.5 Testes unitários (obrigatórios, em `tests/contract/unit/`)

| Alvo | Testes mínimos |
|---|---|
| drift | o JSON Schema gerado é idêntico ao versionado |
| JSON Schema | valida `examples/loja.yaml`; rejeita campo desconhecido, `version: 2`, tipos errados |
| compatibilidade | um schema v1 mínimo (só campos obrigatórios) continua válido; um campo opcional novo não quebra os exemplos |
| exemplos | todo YAML em `examples/**` valida; os sem extra executam com fakes; os com extra ausente são `skip` com motivo |
| segredos | a varredura de `examples/` não encontra padrões de segredo |
| OpenAPI | `docs/api/openapi.v1.yaml` é YAML válido de OpenAPI 3.1 (validação estrutural) e cada rota da tabela H.3.3 existe |

### H.6 Exemplos de features opcionais (em `examples/contrato/`)

| Arquivo | Demonstra |
|---|---|
| `schema.json` | o mesmo `loja` em **JSON** em vez de YAML (formato aceito pelo contrato) |
| `minimo.yaml` | o menor schema válido |
| `validar-com-jsonschema.sh` | validar um schema com uma ferramenta externa usando `schemas/dataipsum-schema.v1.json` |
| `README.md` | explicação e saída esperada |

### H.7 Critérios de aceitação

- **H-01** `schemas/dataipsum-schema.v1.json` existe e é idêntico à saída de `dataipsum schema jsonschema`.
- **H-02** Todos os exemplos do repositório validam, tanto pelo loader quanto pelo JSON Schema.
- **H-03** `docs/api/openapi.v1.yaml` contém as 7 rotas da H.3.3 e a seção de requisitos de segurança.
- **H-04** Os testes de H.5 existem e passam. Os exemplos de H.6 existem e têm README.

### H.8 BDD

```gherkin
# language: pt
Funcionalidade: Contrato do schema

  Cenário: O JSON Schema publicado acompanha o modelo
    Quando eu executo "dataipsum schema jsonschema"
    Então a saída é idêntica a "schemas/dataipsum-schema.v1.json"

  Cenário: Mesmo schema em YAML e JSON
    Dado "examples/loja.yaml" e "examples/contrato/schema.json" com o mesmo conteúdo
    Quando eu gero ambos com seed 1
    Então os dados gerados são idênticos

  Cenário: Todos os exemplos são válidos
    Quando eu executo a suíte de contrato
    Então todo arquivo YAML em "examples/" passa na validação
```

### H.10 Evolução da imagem

- **Fragmento:** nenhum. O JSON Schema é gerado pelo código, e `schemas/`, `examples/` e `docs/` ficam fora da imagem (`.dockerignore`).
- **Testes** (`tests/docker/test_image_contrato.py`): `docker run <img> schema jsonschema` produz saída idêntica a `schemas/dataipsum-schema.v1.json`.
- **Critério H-05:** o teste acima passa.

---

## 3. Integração ponta a ponta (S5)

- **Depende de:** S1–S4 deste doc **e** do S5 do DD-01 (motor integrado).
- **Conteúdo:**
  - testes em `tests/integration/e2e/` que exercitam a **CLI real** com o **motor real**;
  - um provedor LLM fake registrado **só no teste** (plugin de teste com allowlist) e sinks reais;
  - encaixe dos stubs de `ddl_for`/`avro_schema` da trilha E com a implementação da trilha F.
- **Critérios:**
  - **I-01** `dataipsum gen examples/loja.yaml -o out --format parquet --emit-schema ddl,avro --seed 1` retorna código 0; os arquivos, o manifesto e `_schema/` existem.
  - **I-02** O mesmo comando com `--format csv` e `--format jsonl` produz o mesmo número de linhas por tabela.
  - **I-03** (integration) O DDL emitido carrega em Postgres, e `--format postgres` insere os dados sem violar FKs. Uma segunda execução com `resume` não duplica.
  - **I-04** (integration) `--format kafka` publica mensagens desserializáveis com os `.avsc` emitidos.
  - **I-05** (docker) `docker compose run dataipsum gen /schemas/loja.yaml -o /out` funciona como UID 10001.
  - **I-06** `schema export` → `schema import` → `schema validate` completa o round-trip sem erros.
  - **I-07** (docker) A imagem final, com os fragmentos de todas as trilhas e `EXTRAS=all`, passa todos os `tests/docker/test_image_*.py`, o `hadolint` e o `trivy`, e executa I-01 dentro do container. É o fim da evolução prevista no DD-00 §3.12.4.

```gherkin
# language: pt
Funcionalidade: Entrega ponta a ponta

  Cenário: Da CLI ao Parquet com schema emitido
    Quando eu executo "dataipsum gen examples/loja.yaml -o out --format parquet --emit-schema ddl,avro --seed 1"
    Então o código de saída é 0
    E existe "out/_manifest.json" com status "completed"
    E existem arquivos Parquet para "usuarios", "produtos" e "pedidos"
    E existem "out/_schema/ddl/postgres.sql" e um ".avsc" por tabela
```

## 4. Plano de implementação (steps para o `/task-creator`)

| Step | Trilha | Depende de | Paralelo com |
|---|---|---|---|
| S1 | E — Sinks (arquivos M1; Postgres/MySQL/Kafka M3 contra stubs de F) | DD-00 | S2, S3, S4 e DD-01 (A–D) |
| S2 | F — Import/export (**primeiro** `ddl_for` e `avro_schema`; depois o resto do export; import M3) | DD-00 | S1, S3, S4 e DD-01 |
| S3 | G — CLI e compose de desenvolvimento | DD-00 | S1, S2, S4 e DD-01 |
| S4 | H — Contrato do schema e da API | DD-00 | S1, S2, S3 e DD-01 |
| S5 | Integração ponta a ponta | S1–S4 + S5 do DD-01 | — |

Todo step entrega: código, os **testes unitários** da sua seção "Testes unitários", os **exemplos** da sua seção "Exemplos de features opcionais", a **evolução da imagem** da sua seção "Evolução da imagem" (fragmento, se houver, + `tests/docker/test_image_<área>.py` + seção "Impacto na imagem" no PR; o build e o smoke test da imagem rodam em todo step) e os quality gates do DD-00 §3.2 passando.

## 5. Rastreabilidade (RESEARCH → este doc)

| RESEARCH | Onde |
|---|---|
| §1 gravados em arquivos; bancos e Kafka depois | E |
| §2.1 CLI fina (Typer) | G.3.1 |
| §2.2 `dataipsum gen schema.yaml`; flags inline; contrato da UI | G.3.1, H |
| §2.3 import de DDL (sqlglot, PK/FK, inferência por nome, ajuste pelo usuário) | F.3.4 |
| §2.3 export DDL por dialeto: PK/FK, `NOT NULL` por `null_ratio = 0`, `VARCHAR(n)`, `DECIMAL(p,s)` | F.3.1 (N declarado pelo usuário, **decisão que substitui** "maior valor gerado") |
| §2.3 Avro por tabela, logical types, union nula | F.3.2 |
| §2.3 `schema export --format ddl\|avro [--dialect]`; `--emit-schema` + manifesto | F.3.3 |
| §2.3 Avro reutilizado pelo sink Kafka | E.3.3 |
| §2.8 MVP CSV, JSON/JSONL, Parquet | E.3.1 |
| §2.8 depois Postgres (COPY), MySQL, Kafka via `Sink` | E.3.2, E.3.3 |
| §2.8 escrita idempotente (arquivo por chunk + rename atômico; transação por chunk + tabela de controle; producer idempotente key = PK) | E.3 |
| §2.8 manifesto e retomada | DD-00 §3.7 + DD-01 D.3.5; E (substituição) |
| §2.9 imagem (multi-stage, não-root, `ENTRYPOINT`, `EXTRAS`, volumes, `.dockerignore`) | DD-00 §3.12; evolução por trilha em E.10, F.10, G.10, H.10 |
| §2.9 compose de dev dataipsum + Ollama substituindo os scripts elvish | G.3.2 |
| §2.10 UI fora do MVP; contrato YAML/JSON e API FastAPI futura; React + React Flow sugerido | H |
| §3 M1 (sinks de arquivo, export, Docker), M3 (sinks de banco/Kafka, import), M4 (API/UI; aqui só contrato) | S1–S5 |

## 6. Questões em aberto e riscos

- **Risco:** `detoxify`/`torch` com `EXTRAS=toxicity` aumentam muito a imagem.
- **A definir pelo usuário:** metas de tamanho da imagem e de desempenho. Até lá, os testes só medem e registram.
- **Risco:** a substituição de chunks `placeholder` em banco faz `UPDATE` por PK de até `chunk_size` linhas. Com chunks grandes, os lotes de `UPDATE` precisam ser fatiados, o que continua dentro da mesma transação.
- **Para revisão:** os padrões de inferência por nome (F.3.4) e os padrões do import (`rows: 1000`, `range 0..5`, `range 1..3` em pontes).
- **Para revisão:** o formato padrão `parquet` para `gen` sem `--format`.
