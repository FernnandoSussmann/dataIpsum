# DD-00 — Fundação e Contratos

| | |
|---|---|
| **Status** | Proposto (para revisão) |
| **Marco** | M1 |
| **Onda** | 0. É **bloqueante**: o DD-01 e o DD-02 só começam depois deste doc |
| **Fonte** | `RESEARCH.md` §2.1, §2.2, §2.4 (registry/extensibilidade), §2.5 (seed), §2.8 (manifesto) e §4 (formato do YAML) |
| **Docs relacionados** | [DD-01 — Motor de geração](DD-01-motor-de-geracao.md) · [DD-02 — Saídas, interfaces e entrega](DD-02-saidas-interfaces-e-entrega.md) |

---

## 1. Contexto e escopo

Hoje o dataIpsum é um script único (`data_ipsum.py`) em Python 2. Ele gera int, string e float lidos via `raw_input` e imprime tudo em memória. `RESEARCH.md` decidiu **reescrever do zero** em Python 3.12+, como biblioteca importável com uma CLI fina.

Este documento define **tudo o que as outras trilhas precisam compartilhar** para que possam ser implementadas em paralelo, sem se esperarem:

- esqueleto do repositório, tooling e quality gates;
- **formato exato do schema YAML**, que o RESEARCH §4 deixou em aberto e que é resolvido aqui;
- modelo Pydantic do schema e JSON Schema exportável;
- **registry** único de geradores e sinks, com plugins via entry points;
- **interfaces** (`Generator`, `Sink`, `Executor`, `LLMProvider`, `ToxicityClassifier`, `Planner`) e estruturas de dados trocadas entre elas;
- **derivação de seeds** e o sorteio por célula, determinístico e com acesso aleatório O(1);
- **manifesto da execução**;
- façade da biblioteca, hierarquia de erros e *fakes* de teste;
- **imagem Docker base** e o mecanismo pelo qual cada trilha a evolui (§3.12).

O que fica **fora** deste doc: a implementação de tipos, relações, LLM, executores, sinks, import/export, CLI e o compose de desenvolvimento. Isso vive no DD-01 e no DD-02, e cada trilha evolui a imagem pelo próprio fragmento (§3.12).

## 2. Objetivos e não-objetivos

**Objetivos**
- As 8 trilhas do DD-01 e do DD-02 devem poder ser implementadas **simultaneamente**, cada uma tocando só os próprios diretórios.
- Um único modelo de schema (YAML, flags inline e futura UI) com validação estrutural completa e mensagens de erro acionáveis.
- Determinismo total dos dados não-LLM: a mesma seed e o mesmo schema produzem os mesmos bytes, independentemente de worker, ordem de execução ou `chunk_size`.
- Recalcular qualquer célula de qualquer linha em O(1), a partir de `(seed, tabela, coluna, índice)`.
- Retomar execuções a partir do manifesto.
- Extensão por pacotes externos sem alterar o core.

**Não-objetivos**
- Geração criptograficamente segura. O PRNG é estatístico, não serve para segredos.
- Compatibilidade com o código Python 2 ou com o formato de entrada antigo.
- Migração automática entre versões do schema. Existe só o campo `version` e a regra de compatibilidade (trilha H).
- Um formato de manifesto compatível com outras ferramentas.

## 3. Design

### 3.1 Layout do repositório e posse de diretórios

O DD-00 cria **todo o esqueleto**, inclusive os pacotes vazios das trilhas. Cada pacote de trilha nasce com um `register(registry)` vazio. Assim nenhuma trilha precisa editar arquivos de outra, nem o `pyproject.toml`.

```
pyproject.toml, uv.lock, .pre-commit-config.yaml, .gitignore   ← DD-00 (congelados para as trilhas)
security/exceptions.yaml, scripts/check_security_exceptions.py ← DD-00
src/dataipsum/
  __init__.py            façade pública (reexporta api.py)                  ← DD-00
  api.py                 load_schema/validate/plan/generate/resume/export/import ← DD-00
  config.py              RunOptions, leitura de env                          ← DD-00
  errors.py              hierarquia de erros                                 ← DD-00
  registry.py            registry + carga de plugins                         ← DD-00
  seeds.py               derivação de seeds + Draws (sorteio por célula)     ← DD-00
  manifest.py            leitura/escrita atômica do manifesto                ← DD-00
  schema/                models.py, loader.py, inline.py, jsonschema.py      ← DD-00
  contracts/             generator.py, sink.py, executor.py, llm.py,
                         toxicity.py, planner.py, types.py (LogicalType)     ← DD-00
  testing/               fakes.py (FakeSink, FakeExecutor, FakeLLM,
                         FakeToxicity, FakePlanner), builders de schema       ← DD-00
  types/                 ← Trilha A (DD-01)
  relations/             ← Trilha B (DD-01)
  llm/                   ← Trilha C (DD-01)
  execution/             ← Trilha D (DD-01)
  sinks/                 ← Trilha E (DD-02)
  schema_io/             ← Trilha F (DD-02)
  cli/                   ← Trilha G (DD-02)
schemas/, docs/api/, examples/README.md, examples/loja.yaml                  ← Trilha H (DD-02)
examples/<área>/   uma subpasta por área (core, tipos, relacoes, llm, ...)   ← dono da área
docker/Dockerfile.in, scripts/render_dockerfile.py, .dockerignore           ← DD-00
Dockerfile         gerado a partir do template + fragmentos (não editar)     ← DD-00 (script)
docker/fragments/<área>.{build,runtime}.dockerfile                        ← dono da área
docker-compose.yml (dev)                                                   ← Trilha G (DD-02)
tests/docker/     test_image_base.py (DD-00) + test_image_<área>.py         ← dono da área
tests/core/  tests/types/  tests/relations/  tests/llm/  tests/execution/
tests/sinks/ tests/schema_io/ tests/cli/ tests/contract/ tests/integration/
```

**Regra de congelamento.** Depois que o DD-00 for mergeado, `pyproject.toml`, `uv.lock` e os arquivos de `contracts/` só mudam por PR explícito "mudança de contrato", revisado por todas as trilhas afetadas. Por isso o DD-00 já declara **todas** as dependências das trilhas (seção 3.2).

**Legado.** O DD-00 remove `data_ipsum.py` e atualiza o `README.md` para a nova forma de uso. O RESEARCH também pede para remover `study/` e os scripts elvish, mas **eles não existem no repositório**. O step só confirma essa ausência e a registra no PR.

### 3.2 Tooling, dependências e quality gates

- **Python** `>=3.12`, com gerenciador **uv**, build backend `hatchling`, src layout e `uv.lock` versionado.
- **Dependências base** (instalação enxuta), cada uma com seu motivo:
  - `pydantic>=2`: modelo e validação do schema;
  - `pyyaml`: leitura do YAML;
  - `typer`: CLI;
  - `numpy`: sorteio vetorizado;
  - `pyarrow`: formato colunar interno e Parquet;
  - `faker`: listas de nomes por locale;
  - `psutil`: monitor de recursos;
  - `httpx`: clientes Ollama e OpenAI-compatível;
  - `sqlglot`: export de DDL já no M1.
- **Extras opcionais.** `ray`, `postgres`, `mysql` e `kafka` vêm do RESEARCH §2.1; `toxicity` e `anthropic` são **acréscimos deste design**.

  | Extra | Pacotes | Origem |
  |---|---|---|
  | `ray` | `ray[default]` | RESEARCH |
  | `postgres` | `psycopg[binary]>=3` | RESEARCH |
  | `mysql` | `PyMySQL` (Python puro, sem compilador na imagem slim) | RESEARCH |
  | `kafka` | `confluent-kafka[avro,schemaregistry]` | RESEARCH |
  | `toxicity` | `detoxify` (traz `torch`, que é pesado; por isso fica fora da base) | **novo** |
  | `anthropic` | `anthropic` (SDK oficial) | **novo** |
  | `all` | a união de todos os extras | **novo** |

- **Dependências de dev** (`[dependency-groups] dev`): `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`, `types-PyYAML`, `pre-commit`, `bandit`, `semgrep`, `pip-audit`, `fastavro` (validação dos `.avsc` nos testes) e `testcontainers` (usado nos testes de integração M3, marcados).
- **Quality gates.** Obrigatórios em todo step de toda trilha; o pre-commit e a CI rodam os mesmos comandos.
  1. `uv run ruff check .`
  2. `uv run ruff format --check .`
  3. `uv run mypy --strict src`
  4. `uv run pytest -m "not integration and not slow"` com cobertura ≥ **85%** por pacote de trilha.
  5. Testes marcados com `integration` (Docker/testcontainers), `slow`, `ray` (cluster Ray local) ou `docker` (build de imagem/compose) rodam em job separado e são obrigatórios nos steps que os criam. Os markers ficam registrados no `pyproject.toml` (`--strict-markers`).
  6. **SAST:** `bandit` e `semgrep` com as regras OWASP (§3.2.1).
  7. **SCA:** `pip-audit` sobre o `uv.lock` e OWASP Dependency-Check (§3.2.1).
  8. **Segredos e Dockerfile:** `gitleaks` e `hadolint` (§3.2.1).
- **Pre-commit hook obrigatório.** Os gates rodam num hook de pre-commit (§3.2.1), e a CI roda exatamente a mesma configuração com `pre-commit run --all-files`. Nenhum commit ou merge passa com um gate falhando.
- **Regra transversal: testes unitários.** Esta regra vale para o DD-00, o DD-01 e o DD-02.
  - Todo step entrega **testes unitários** em `tests/<área>/unit/`, cobrindo cada módulo que ele cria. A lista mínima de testes fica na seção "Testes unitários" de cada doc.
  - Os unitários não dependem de rede, Docker, GPU ou LLM real. Usam fakes (§3.11) e rodam no gate 4.
  - Testes de integração ficam em `tests/<área>/integration/` com `@pytest.mark.integration`.
  - Um step sem os unitários listados **não** é considerado concluído.
- **Regra transversal: exemplos de features opcionais.**
  - **Features opcionais** são:
    - os extras (`ray`, `postgres`, `mysql`, `kafka`, `toxicity`, `anthropic`);
    - opções de schema com valor padrão ou desligadas por padrão, como `seed`, `null_ratio`, `invalid_ratio`, `format`, `locale` por coluna, cardinalidades, `coverage`, `mode: pool`, modos de `toxicity`, `on_failure: placeholder` e provedores LLM alternativos;
    - opções de CLI, como flags inline, `--emit-schema`, `--dialect`, `resume`, `--executor ray` e tetos de CPU/RAM.
  - O step que **implementa** uma feature opcional também entrega um exemplo executável dela em `examples/<área>/`:
    - um YAML de schema e/ou um script `.sh` com o comando da CLI;
    - um `README.md` da pasta que explica o que o exemplo demonstra, o extra necessário e a saída esperada.
  - Cada área escreve só na **própria subpasta**, o que evita conflito entre trilhas paralelas. As áreas são `core`, `tipos`, `relacoes`, `llm`, `execucao`, `sinks`, `schema-io`, `cli-docker` e `contrato`.
  - A trilha H mantém o índice `examples/README.md` e o teste `tests/contract/test_examples.py`. Esse teste valida **todos** os `examples/**/*.yaml` com `dataipsum.validate`. Também executa com `FakeLLM` e `FakeSink` os que não dependem de extra, e pula (`skip`, com o motivo) os que dependem de um extra não instalado.
- **Regra transversal: padrões de código.** Escrita funcional e concisa, nomes que descrevem o comportamento e comentários só quando o código não consegue expressá-lo (§3.10). Vale para o DD-00, o DD-01 e o DD-02, e é verificada pelo ruff (gate 1) e pela revisão de cada step.
- **Entry points** declarados já no DD-00:
  - `[project.scripts] dataipsum = "dataipsum.cli:app"`;
  - grupos de plugin `dataipsum.generators` e `dataipsum.sinks`.

### 3.2.1 Pre-commit hook: quality gates e segurança

O S1 entrega `.pre-commit-config.yaml` e o documenta no README do repositório: `uv run pre-commit install --hook-type pre-commit --hook-type pre-push`. Todos os hooks de Python são **locais** e usam `uv run`, com as versões travadas no `uv.lock`, para que o hook, a CI e o ambiente de desenvolvimento usem as mesmas versões. Hooks de terceiros (`gitleaks`, `hadolint`) têm `rev` fixo.

**Hooks no estágio `pre-commit`** (a cada commit):

| Hook | Categoria | Comando / regra | Falha quando |
|---|---|---|---|
| `ruff-check` | lint + padrões de código (§3.10) | `uv run ruff check .` | qualquer violação |
| `ruff-format` | formatação | `uv run ruff format --check .` | arquivo não formatado |
| `mypy` | checagem de tipos | `uv run mypy --strict src` | qualquer erro de tipo |
| `pytest-unit` | testes | `uv run pytest -m "not integration and not slow and not ray and not docker" --cov --cov-fail-under=85` | teste falho ou cobertura < 85% |
| `bandit` | **SAST** Python | `uv run bandit -r src -c pyproject.toml` | achado de severidade ≥ média |
| `semgrep` | **SAST** OWASP | `uv run semgrep scan --config p/owasp-top-ten --config p/python --error --metrics=off src` | qualquer achado com severidade `ERROR` |
| `pip-audit` | **SCA** | `uv export --frozen --no-hashes` → `uv run pip-audit --strict -r -` (base + todos os extras + dev) | qualquer vulnerabilidade conhecida (base OSV/PyPI) |
| `gitleaks` | segredos | `gitleaks protect --staged` | segredo no diff |
| `dockerfile-render` | imagem | `uv run python scripts/render_dockerfile.py --check` | fragmento inválido (§3.12.2) ou `Dockerfile` diferente do gerado |
| `hadolint` | Dockerfile | `hadolint Dockerfile` | regra de severidade `warning` ou maior |

**Hooks no estágio `pre-push`** (e na CI), mais pesados:

| Hook | Categoria | Comando / regra | Falha quando |
|---|---|---|---|
| `owasp-dependency-check` | **SCA** OWASP | OWASP Dependency-Check (imagem oficial `owasp/dependency-check`, versão fixa) sobre o `uv.lock` e o requirements exportado; chave em `NVD_API_KEY` (env) | CVSS ≥ 7.0 (`--failOnCVSS 7`) |
| `pytest-integration` | testes | `uv run pytest -m "integration or slow"` | teste falho |

**Na CI**, com o marker `docker` (§3.12.3, obrigatório em todo step): build da imagem, smoke tests e `trivy image` na imagem construída, que falha em vulnerabilidades `HIGH` ou `CRITICAL` com correção disponível.

**Trade-off.** Dependency-Check e testes de integração ficam no `pre-push`, e não no `pre-commit`, por três motivos:
- exigem Docker;
- baixam a base NVD;
- levam minutos.

Com isso cada commit continua rápido, sem abrir mão da checagem antes de o código sair da máquina, e a CI roda tudo de novo.

**Exceções de segurança:**
- ficam só em `security/exceptions.yaml`, com ID do achado (CVE, regra do bandit/semgrep), ferramenta, justificativa, responsável e **data de expiração**;
- um script do hook traduz esse arquivo para os argumentos de cada ferramenta (`--ignore-vuln` do pip-audit, `--suppression` do Dependency-Check, lista de regras ignoradas do bandit/semgrep);
- exceção vencida faz o hook falhar.

**Proibido:**
- `git commit --no-verify` como prática; a CI roda os mesmos hooks e bloqueia o merge;
- `# nosec` ou `# nosemgrep` inline sem entrada correspondente em `security/exceptions.yaml`.

### 3.3 Formato do schema YAML (proposta concreta, resolve RESEARCH §4)

O schema é um documento YAML (ou JSON equivalente) validado pelo modelo Pydantic. **Este é o contrato da futura UI** (trilha H). Exemplo completo:

```yaml
version: 1                       # obrigatório; versão do formato
name: loja                       # opcional; namespace (Avro, nomes de arquivo)
seed: 42                         # opcional; inteiro 0..2^63-1. Ausente => sorteada e gravada no manifesto
locale: pt_BR                    # padrão pt_BR; sobrescrevível por coluna
chunk_size: 10000                # padrão 10000; 100..1_000_000
limits:
  max_rows_total: 100000000      # guardrail; padrão 1e8

llm:
  default_provider: local
  providers:
    local:
      kind: ollama               # ollama | openai_compatible | anthropic
      base_url: http://ollama:11434
      model: llama3.1:8b
      max_concurrency: 2
      timeout_s: 120
      temperature: 0
    nuvem:
      kind: anthropic
      model: <id-do-modelo>
      api_key_env: ANTHROPIC_API_KEY   # NOME da variável; nunca a chave em si
      max_concurrency: 4
  retry: {max_attempts: 5, base_delay_s: 1, max_delay_s: 60}

tables:
  - name: usuarios
    rows: 1000                   # só em tabelas raiz
    primary_key: {columns: [id], strategy: sequence, start: 1}
    columns:
      - {name: id, type: int}
      - {name: nome, type: nome_proprio, max_length: 120}
      - {name: cpf, type: cpf, format: masked, invalid_ratio: 0.02}
      - {name: bio, type: string, max_length: 200, null_ratio: 0.1}
      - {name: criado_em, type: timestamp, params: {min: "2024-01-01T00:00:00Z", max: "2025-12-31T23:59:59Z"}}

  - name: produtos
    rows: 200
    primary_key: {columns: [id], strategy: seeded_uuid}
    columns:
      - {name: id, type: uuid}
      - {name: titulo, type: string, max_length: 80}
      - {name: preco, type: decimal, params: {precision: 10, scale: 2, min: "1.00", max: "5000.00"}}

  - name: pedidos                 # tabela filha: nº de linhas DERIVADO da cardinalidade
    primary_key: {columns: [id], strategy: sequence}
    rows_from:
      via: usuario_id            # coluna ref que dirige a contagem
      relation: one_to_many      # one_to_one | one_to_many | many_to_many | thread
      cardinality: {range: {min: 0, max: 5}}
    columns:
      - {name: id, type: int}
      - {name: usuario_id, type: ref, params: {table: usuarios}}
      - {name: produto_id, type: ref, params: {table: produtos, distribution: {zipf: {s: 1.1}}}}
      - name: comentario
        type: llm_post
        max_length: 500
        params:
          provider: local
          prompt: "Escreva um comentário curto de {usuario_id.nome} sobre o produto {produto_id.titulo}."
          mode: pool
          pool_size: 50
          toxicity: ratio
          toxicity_ratio: 0.05
          on_failure: pending
```

**Campos de topo**

| Campo | Tipo | Obrig. | Padrão | Regra |
|---|---|---|---|---|
| `version` | int | sim | — | só `1` é aceito neste marco |
| `name` | identificador | não | `dataipsum` | regex de identificador (§6) |
| `seed` | int | não | sorteada | 0 ≤ seed < 2^63 |
| `locale` | str | não | `pt_BR` | tem de existir no registry de locales (trilha A) |
| `chunk_size` | int | não | 10000 | 100 ≤ x ≤ 1.000.000 |
| `limits.max_rows_total` | int | não | 100.000.000 | soma planejada de linhas ≤ limite |
| `llm` | objeto | se houver coluna LLM | — | ver trilha C |
| `tables` | lista | sim | — | 1..200 tabelas; nomes únicos |

**Campos de tabela**

| Campo | Regra |
|---|---|
| `name` | identificador único |
| `rows` | int ≥ 0. **Obrigatório em tabela raiz e proibido em tabela com `rows_from`** |
| `rows_from` | `{via, relation, cardinality?, coverage?, pair?}`. Semântica na trilha B |
| `thread` | só quando `rows_from.relation = thread`. Semântica nas trilhas B e C |
| `primary_key` | `{columns: [..], strategy: sequence\|seeded_int\|seeded_uuid\|composite, start?, step?}`. É obrigatório. `composite` só é válido em `many_to_many` |
| `locale` | sobrescreve o locale do schema |
| `columns` | 1..500 colunas com nomes únicos |

**Campos de coluna**

| Campo | Regra |
|---|---|
| `name` | identificador único na tabela; nomes reservados em tabelas `thread` (trilha B) |
| `type` | nome registrado no registry (§3.4) |
| `params` | objeto livre, validado pelo `validate_params` do gerador |
| `null_ratio` | float 0..1, padrão 0. Deve ser 0 em colunas de PK e na coluna `via` |
| `invalid_ratio` | float 0..1, padrão 0. **Só é aceito se o gerador declarar `supports_invalid`** (CPF, RG, cartão, e-mail). Em qualquer outro tipo, é erro de validação |
| `format` | `masked` \| `unmasked`. Só vale para geradores que declaram `supports_format` |
| `max_length` | int ≥ 1. **Obrigatório** em `string`, opcional em `nome_proprio` (padrão 120) e em `llm_*`. O gerador produz valores com 0..N caracteres, e o DDL usa `VARCHAR(N)` |
| `locale` | sobrescreve o locale da tabela |

**Flags inline.** `schema/inline.py` converte flags em um `Schema` com uma única tabela. A gramática é `--col nome:tipo[:pk][:chave=valor...]`, e `--rows N` define o número de linhas. O parsing das flags é da trilha G; a função `build_inline_schema(table, rows, cols) -> Schema` é do DD-00.

**Validação em camadas.** O loader executa, em ordem, e acumula todos os erros de uma camada antes de falhar:

1. limites do documento (§6);
2. estrutura (Pydantic);
3. referências de nomes: tabelas, colunas, tipos no registry;
4. validação delegada ao registry:
   - `Generator.validate_params` (trilhas A e C);
   - `Planner.validate` (grafo e relações, trilha B);
   - `TemplateValidator` (variáveis de prompt, trilha C).

Cada erro traz um **caminho** (`tables[2].columns[3].params.max`) e uma mensagem em pt-BR.

**JSON Schema.** `schema/jsonschema.py` exporta o JSON Schema do modelo Pydantic. A trilha H versiona esse arquivo e testa que ele não diverge do modelo.

### 3.4 Registry e plugins

- Há um registry único com dois namespaces: `generators` (nome do tipo → classe `Generator`) e `sinks` (nome do formato → classe `Sink`). Locales, provedores LLM e classificadores são sub-registries do mesmo objeto: `locales`, `llm_providers`, `toxicity`.
- **Built-ins são registrados da mesma forma que plugins.** Ao inicializar o registry, os `register(registry)` dos pacotes internos (`types`, `relations`, `llm`, `sinks`) são chamados em ordem fixa.
- **Plugins externos** são carregados dos grupos `dataipsum.generators` e `dataipsum.sinks` e só entram se **permitidos**. Controle:
  - `DATAIPSUM_PLUGINS=nome1,nome2` define uma allowlist de nomes de distribuição;
  - `DATAIPSUM_PLUGINS=*` permite todos;
  - sem a variável, **nenhum** plugin externo é carregado e cada plugin encontrado gera um aviso;
  - `--no-plugins` na CLI força desligado.
- Conflito de nome:
  - um plugin **não pode** sobrescrever um built-in (`RegistryConflictError`);
  - dois plugins com o mesmo nome também geram erro.
- Cada plugin carregado é logado com nome, versão e origem.

### 3.5 Contratos (interfaces)

As assinaturas abaixo estão resumidas; os `Protocol`s ficam em `contracts/`.

**`LogicalType`**: tipo canônico que cada gerador declara. É consumido pelo DDL, pelo Avro, pelos sinks e pelo schema Arrow.

- `string(max_length)`, `text`, `char(length)`, `int64`, `int32`, `float64`, `decimal(precision, scale)`, `boolean`, `date`, `time`, `timestamp(tz: bool)`, `uuid`, `json`, `array(item: LogicalType, max_items)`;
- `nullable: bool`, que vale `null_ratio > 0`.
- `to_arrow_type(LogicalType) -> pyarrow.DataType`, em `contracts/types.py`: mapeamento único usado pelo motor e pelos sinks (decimal → decimal128(p,s), timestamp → timestamp[ms] com ou sem tz, date → date32, time → time32[s|ms], uuid → string, json → string, array → list).

**`Generator`**
- Atributos: `name`, `supports_invalid`, `supports_format`, `deterministic` (é `False` só nos tipos `llm_*`), `draw_slots` (quantos slots de sorteio usa por célula, ver §3.6).
- `validate_params(column, ctx) -> list[ValidationError]`.
- `logical_type(column) -> LogicalType`.
- `depends_on(column) -> list[str]`: colunas **determinísticas da mesma linha** de que o gerador precisa. Por exemplo, `email` com `name_column`. O motor gera as colunas em ordem topológica dessas dependências e as entrega por `GenContext.same_row`. Ciclo ou dependência de coluna `llm_*` é `SchemaError`. O padrão é `[]`.
- `implied_columns(column) -> list[ColumnSpec]`: colunas que o tipo acrescenta à tabela. Os tipos `llm_*` acrescentam `is_offensive` e `is_placeholder`. A normalização do schema acrescenta essas colunas **ao fim** da tabela e deduplica por nome; o usuário não pode declarar colunas com esses nomes.
- `generate(column, batch: RowBatch, draws: Draws, ctx: GenContext) -> pyarrow.Array`:
  - **vetorizado**, recebe N linhas e devolve N valores;
  - `batch.rows` é um `ndarray[int64]` de índices globais, nem sempre contíguos: `row_at` pede índices soltos;
  - `batch.invalid_mask` é calculado pelo motor.
  - O motor aplica `null_ratio` **depois** do gerador, com o slot reservado 0. O gerador nunca produz nulos por conta própria.
- `GenContext` expõe:
  - `locale`;
  - `same_row(column_names) -> dict[str, pyarrow.Array]`: colunas determinísticas já geradas no mesmo lote;
  - `parent_rows(table, parent_indices, columns) -> dict[str, pyarrow.Array]`: recálculo local de linhas de outra tabela (trilha B).

**`Planner`** (implementado pela trilha B)
- `validate(schema) -> list[ValidationError]`.
- `implied_columns(table) -> list[ColumnSpec]`: colunas acrescentadas no **nível da tabela**. Hoje, as colunas de tabelas `thread`: `seq`, `autor`, `timestamp`, `texto`, `is_offensive` e `is_placeholder` (DD-01, B.3.6). A normalização do schema chama esse método junto com o `Generator.implied_columns`: acrescenta ao fim, rejeita colisão com colunas do usuário e deduplica por nome.
- `plan(schema, seed, chunk_size) -> RunPlan`.
- `pk_at(table, indices) -> pyarrow.Array`.
- `parent_index_of(table, chunk, batch) -> ndarray`.
- `row_at(table, indices, columns) -> dict[str, pyarrow.Array]`.

**`RunPlan`**
- `order`: tabelas em ordem topológica.
- Por tabela:
  - `rows` (total);
  - `chunks: list[ChunkSpec]`, onde `ChunkSpec = {id: int ≥ 1, first_row: int, rows: int, parent: {table, first_index, count, first_child_offset}?}`;
  - para tabelas derivadas, o prefixo de offsets por chunk.
- Serializável em JSON, porque vai para o manifesto.

**`ChunkTask` / `ChunkResult`**: unidade de trabalho do executor. **Autocontida e picklable**: contém schema normalizado, seed raiz, `ChunkSpec`, destino do sink e opções. Não tem estado compartilhado.
- `ChunkResult = {table, chunk_id, status: done|pending|pending_llm|failed, rows, sink_ref, sha256?, flags: {placeholders, offensive, toxicity_exhausted, thread_fallbacks}, blocked_by?, error?}`. `pending` + `blocked_by` indica um chunk filho que espera um chunk pai não concluído (DD-01, C.3.7).

**`Executor`**
- `submit(tasks: Iterable[ChunkTask]) -> Iterator[ChunkResult]`: resultados fora de ordem.
- `set_concurrency(n)`, `concurrency`.
- `shutdown(wait: bool)`.
- Mais um `LLMLimiter`, obtido por `executor.llm_limiter(provider_name, max_concurrency)`, com semântica de semáforo (context manager). É o mecanismo que limita chamadas LLM por provedor entre processos e nós (trilha D).

**`Sink`**
- `open(run: RunContext, table: TableSpec, arrow_schema) -> None`.
- `write_chunk(chunk_id: int, batch: pyarrow.RecordBatch | Iterator[RecordBatch]) -> SinkReceipt`: **idempotente**; reescrever o mesmo `chunk_id` substitui atomicamente.
- `chunk_state(chunk_id) -> absent|committed`.
- `close() -> None`.
- `capabilities = {atomic_chunk: bool, replace_chunk: bool, referential_integrity: bool}`. `referential_integrity = true` nos sinks de banco: o destino rejeita FK órfã, então chunks filhos esperam os chunks pais (DD-01, C.3.7).

**`LLMProvider`**
- `complete(req: LLMRequest) -> LLMResponse`.
  - `LLMRequest = {system, prompt, json_schema?, max_tokens, temperature, seed?}`.
  - `LLMResponse = {text, finish_reason, usage?}`.
- Atributos: `supports_json_schema`, `supports_seed`.
- Erros tipados: `ProviderUnavailable`, `ProviderRateLimited`, `ProviderRefusal`, `ProviderBadResponse`.

**`ToxicityClassifier`**
- `score(texts: list[str]) -> list[float]` (0..1).
- `name`, `available() -> bool`.

### 3.6 Seeds e sorteio por célula (algoritmo novo, com pseudo-código)

**Requisitos (RESEARCH §2.5):**
- seed opcional, sorteada e registrada quando ausente;
- seeds derivadas por **tabela → coluna → chunk**;
- um chunk reprocessado em outro worker gera exatamente o mesmo resultado;
- qualquer linha é recalculável localmente a partir de `(seed, tabela, índice)`.

**Derivação hierárquica**, com `u64` = inteiro sem sinal de 64 bits e aritmética módulo 2^64:

```
derive(parent: u64, label: str) -> u64 =
    int.from_bytes(blake2b(parent.to_bytes(8,'little') + label.encode('utf-8'),
                           digest_size=8).digest(), 'little')

seed_table(t)        = derive(root_seed, "t:" + t)
seed_column(t, c)    = derive(seed_table(t), "c:" + c)
seed_chunk(t, c, k)  = derive(seed_column(t, c), "k:" + str(k))
seed_relation(t, r)  = derive(seed_table(t), "r:" + r)         # cardinalidade, permutações
```

**Sorteio por célula**, counter-based, vetorizado em numpy. Um sorteio é uma função pura de (coluna, linha global, slot), sem estado sequencial:

```
mix(x):                                   # finalizador SplitMix64
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9
    x = (x ^ (x >> 27)) * 0x94D049BB133111EB
    return x ^ (x >> 31)

draw_u64(seed_col, row, slot) = mix( mix(seed_col + row * 0x9E3779B97F4A7C15)
                                     + slot * 0xD1B54A32D192ED03 )
uniform(seed_col, row, slot)  = (draw_u64(...) >> 11) * 2^-53          # [0,1)
integers(lo, hi)              = lo + floor(uniform * (hi - lo))       # se hi-lo ≤ 2^53
                                (acima disso: draw_u64 com rejeição de Lemire)
```

`Draws` embrulha isso para um `RowBatch`. `draws.uniform(slot)`, `draws.integers(slot, lo, hi)`, `draws.choice(slot, n)` e `draws.normal(slot)` (Box-Muller com os slots `slot` e `slot+1`) devolvem arrays de tamanho N.

**Slots reservados**
- 0: nulo (`uniform < null_ratio` ⇒ nulo).
- 1: inválido (`uniform < invalid_ratio` ⇒ `invalid_mask`).
- 2..63: livres para o gerador.
- Amostragem por rejeição usa slots crescentes a partir de 64, com um teto de tentativas declarado pelo gerador.

**Por que counter-based em vez de um PRNG sequencial por chunk (trade-off):**

| Critério | PRNG sequencial por chunk | Counter-based por célula (escolhido) |
|---|---|---|
| Recalcular a linha i do pai (`row_at`) | O(tamanho do chunk) | **O(1)** |
| Consumo variável (rejeição) desloca linhas seguintes | sim | **não** |
| Resultado depende de `chunk_size` | sim | **não** |
| Vetorização | boa | boa (ops uint64 do numpy) |
| Qualidade estatística | PCG64/Philox | SplitMix64: suficiente para dados sintéticos, não criptográfica |

A hierarquia tabela → coluna → chunk do RESEARCH é respeitada:
- `seed_chunk` existe e é usado para aleatoriedade **com escopo de chunk que não vira dado**, como o jitter de backoff e a ordem interna de trabalho;
- os **dados** são sorteados por célula a partir de `seed_column` e do índice global da linha, e o índice global determina o chunk;
- por isso um chunk reprocessado, em qualquer worker, é bit-a-bit idêntico.

A seed enviada ao LLM é `seed_llm(t, c, row) = derive(seed_column(t, c), "llm:" + str(row))`. Ela é independente de `chunk_size`, o que preserva a chave do cache LLM entre execuções (trilha C).

**Proibido nas trilhas:** usar `random`, `numpy.random` global, `Faker.seed()` ou qualquer fonte de aleatoriedade que não seja `Draws` / `seed_*`. Faker só pode ser usado como **fonte de listas** (nomes, sobrenomes); o índice escolhido vem de `Draws`. Um teste de arquitetura em `tests/core/` falha se `import random` ou `np.random.` aparecer em `src/dataipsum/` fora de `seeds.py`.

**Seed ausente:** `secrets.randbits(63)`, gravada no manifesto com `seed_source: "random"`.

### 3.7 Manifesto da execução

- **Local:** `<out>/_manifest.json`. É escrito **só pelo processo driver**; workers devolvem `ChunkResult` e não tocam no arquivo.
- **Escrita atômica:** grava em `<out>/._manifest.json.tmp-<uuid>`, faz `fsync` do arquivo, `os.replace` e `fsync` do diretório.
- **Frequência:** a cada 50 chunks concluídos, a cada 5 s e no fim.
  - **Trade-off:** reescrever o JSON inteiro a cada chunk seria O(n²).
  - **Consequência aceita:** se o processo cair, chunks concluídos após o último flush são refeitos no `resume`. Isso é seguro porque a escrita é idempotente (DD-02, trilha E).
- **Conteúdo**, versionado por `manifest_version: 1`:
  - `run_id` (uuid4), `dataipsum_version`, `created_at`, `updated_at`;
  - `status: running|completed|partial|failed`;
  - `seed`, `seed_source: user|random`, `chunk_size`;
  - `schema` (normalizado, com padrões aplicados) e `schema_sha256`;
  - `sink: {kind, options}`, com opções **sanitizadas** (§6);
  - `plan` (o `RunPlan`);
  - `chunks: {<tabela>: {<chunk_id>: {status, rows, attempts, sink_ref, sha256?, flags, blocked_by?, error?}}}`. `blocked_by: [{table, chunk_id}]` só aparece em chunks `pending` que esperam um chunk pai (DD-01, C.3.7);
  - `status` de cada chunk ∈ `pending | done | pending_llm | failed`;
  - `llm: {providers_used: [{name, kind, model}]}`;
  - `emitted_schemas: [{format: ddl|avro, dialect?, table?, path, sha256}]`, preenchido por `--emit-schema` (DD-02, trilha F).
- **Regras de retomada** (implementadas pela trilha D, DD-01):
  - `resume` usa o schema **embutido** no manifesto;
  - se o usuário passar um schema cujo hash difere, `ManifestMismatchError`;
  - se a versão major do dataipsum difere, erro.

### 3.8 Façade da biblioteca (`dataipsum.api`)

| Função | Responsável pela implementação real |
|---|---|
| `load_schema(source: Path \| str \| dict) -> Schema` | DD-00 |
| `validate(schema) -> ValidationReport` | DD-00 + delegações |
| `plan(schema, options) -> RunPlan` | trilha B |
| `generate(schema, options: RunOptions) -> RunResult` | trilha D |
| `resume(out_dir, options) -> RunResult` | trilha D |
| `export_schema(schema, format, dialect?, out_dir) -> list[Path]` | trilha F |
| `import_ddl(sql_text, dialect) -> Schema` (M3) | trilha F |

- `RunOptions`:
  - `out_dir`;
  - `sink: {kind, options}`;
  - `seed?`, `chunk_size?`;
  - `executor: local|ray`;
  - `cpu_max=70`, `mem_max=60`;
  - `max_rows?`;
  - `llm_on_failure?`;
  - `emit_schema: list[ddl|avro]`, `dialect`;
  - `allow_plugins`;
  - `cache_dir?`.
- `RunResult = {run_id, status, manifest_path, tables: {name: rows}, pending_chunks}`.
- Antes de cada trilha terminar, a façade chama o módulo dela, que existe como esqueleto e levanta `NotImplementedError("trilha X")`. Os testes do DD-00 usam os fakes.
- **Precedência de configuração:** flags da CLI > variáveis de ambiente `DATAIPSUM_*` > schema > padrões.

### 3.9 Erros

`DataIpsumError` é a raiz. Abaixo dela:

- `SchemaError`, com a lista de `ValidationError(path, message)`;
- `RegistryConflictError`, `PluginNotAllowedError`;
- `PlanError`;
- `ManifestError` → `ManifestMismatchError`;
- `SinkError`;
- `ExecutorError`;
- `LLMError` → `ProviderUnavailable`, `ProviderRateLimited`, `ProviderRefusal`, `ProviderBadResponse`;
- `ResourceLimitError`;
- `OutputDirError`.

Mensagens em pt-BR, nunca com segredos.

### 3.10 Padrões de código do projeto

Esta seção vale para **todo** o código do projeto: DD-00, todas as trilhas do DD-01 e do DD-02, testes e exemplos em Python. A revisão de cada step verifica esses padrões.

**Estilo funcional e conciso**
- Transformações de coleções usam `map`, `filter` e `functools.reduce`, ou os equivalentes idiomáticos (compreensões e expressões geradoras), no lugar de `for` com acumulador (`lista.append`, `total += ...`, `dict[k] = ...` dentro de laço).
- Funções são **puras** sempre que possível: sem efeito colateral e sem mutar argumentos. O resultado depende só das entradas.
- Estruturas imutáveis por padrão: `@dataclass(frozen=True)`, `tuple` e `frozenset`. Mutação é local e explícita.
- Funções curtas, com uma responsabilidade cada, compostas entre si, em vez de funções longas com vários passos.
- **Onde o laço explícito é aceito**, e só onde deixa o código mais claro:
  - **dados em volume** (colunas, chunks): prefira operações vetorizadas de `numpy`/`pyarrow` a `map` ou a laços por linha. Iterar linha a linha em Python dentro de geradores é proibido, porque a vetorização é requisito do DD-01;
  - **efeitos colaterais inerentemente sequenciais**: laço de retry com backoff, laço de eventos do driver/monitor, escrita em disco ou em rede.

**Nomes que descrevem o comportamento**
- Funções usam verbo + objeto e dizem o que fazem (`derive_column_seed`, `build_chunk_plan`, `sanitize_sink_options`), não como são implementadas nem nomes genéricos como `process`, `handle` ou `do_it`.
- Variáveis dizem o que contêm (`parent_indices`, `pending_chunks`, `max_length`). Nada de `x`, `tmp`, `data`, `aux` ou `res`.
- Booleanos começam com `is_`, `has_`, `can_` ou `should_` (`is_valid_cpf`, `has_llm_columns`).
- Abreviações só quando são termos do domínio já usados nos contratos: `pk`, `fk`, `dv`, `llm`, `ddl`, `rng`.
- Nomes de uma letra só em lambdas triviais ou em índices matemáticos dentro da implementação de um algoritmo documentado, como Feistel (DD-01, B.3.2) ou SplitMix64 (§3.6).
- Identificadores de código seguem os nomes em inglês dos contratos. Nomes de tipos do domínio brasileiro ficam como no schema (`cpf`, `rg`, `nome_proprio`).

**Comentários só quando o código não consegue expressar o comportamento**
- Um comentário explica o **porquê**: a regra de negócio externa (ex.: pesos do mod 11 do CPF, RFC 2606), a decisão não óbvia, o trade-off ou o *workaround*. Ele nunca repete o que o código diz.
- Antes de comentar, tente renomear ou extrair uma função com nome descritivo. Comentar é o último recurso.
- Proibidos: comentário que parafraseia a linha seguinte, código comentado, banners de seção e `TODO` sem issue.
- A mesma regra vale para docstrings. Elas só existem quando nome, tipos e assinatura não bastam para entender a semântica, como os `Protocol`s de `contracts/` que precisam dizer o que o implementador deve garantir.

**Como é verificado**
- O ruff do `pyproject.toml` (S1) habilita, além dos padrões, as regras:
  - `C4` (compreensões);
  - `PERF` (ex.: `PERF401`, laço que monta lista);
  - `SIM` (simplificações);
  - `FURB` (refurb);
  - `N` (nomes PEP 8);
  - `E741` (nomes ambíguos);
  - `ERA` (código comentado);
  - `RET` (retornos).
- Nenhuma dessas regras pode ser desligada globalmente. Um `# noqa` pontual precisa de justificativa na mesma linha.
- O agente de revisão de cada step (`/implement-step`) confere os pontos que ferramenta não consegue checar: laço que deveria ser `map`/`filter`/`reduce`, nomes que não descrevem o comportamento e comentários desnecessários. Violação reprova o step.

### 3.11 Fakes de teste (`dataipsum.testing`)

Os fakes permitem que cada trilha teste sem as outras:
- `FakeSink`: guarda os batches em memória e simula falha no chunk N.
- `FakeExecutor`: executa em série, no mesmo processo; o `LLMLimiter` é um contador.
- `FakeLLM`: respostas roteirizadas, falha programável e JSON válido/inválido.
- `FakeToxicity`: marca como ofensivo qualquer texto que contenha `"#ofensivo"`.
- `FakePlanner`: só tabelas raiz; `pk_at` = sequência.
- `SchemaBuilder`: fluent, para montar schemas em testes.

### 3.12 Imagem Docker: base e evolução

A imagem nasce **no DD-00** (step S5) e **evolui a cada step** que muda o projeto, em vez de ser construída só no fim. Assim, desde o primeiro merge existe uma imagem que funciona, e cada trilha é responsável por mantê-la funcionando com a sua mudança (RESEARCH §2.9).

#### 3.12.1 Imagem base

- **Estágio `build`:**
  - parte de `python:3.12-slim` (tag e digest fixos);
  - copia o binário `uv` de `ghcr.io/astral-sh/uv:<versão fixa>`;
  - copia `pyproject.toml` e `uv.lock` **primeiro**, para aproveitar o cache de camadas;
  - roda `uv sync --frozen --no-dev --no-editable`, com `--extra <x>` para cada item de `ARG EXTRAS` (lista separada por vírgula, padrão vazio);
  - depois copia `src/` e instala o pacote no venv.
- **Estágio final:**
  - parte de `python:3.12-slim`;
  - copia **só** o `/app/.venv`: sem compiladores, sem cache do uv e sem código de teste;
  - cria o usuário `dataipsum` (UID/GID 10001) e roda com `USER 10001`;
  - `ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1`;
  - `WORKDIR /work`;
  - `VOLUME ["/out"]`. O schema é montado em `/schemas`, somente leitura;
  - `LABEL org.opencontainers.image.version` com a versão do pacote (`ARG VERSION`);
  - `ENTRYPOINT ["dataipsum"]` e `CMD ["--help"]`. No S5 a CLI ainda é o esqueleto do S1 (§8, item 4) e é substituída pela CLI completa da trilha G sem mudar o entrypoint.
- **Configuração em runtime só por variáveis de ambiente:** `DATAIPSUM_*`, lidas por `config.py` (§3.8). A imagem **nunca** embute segredos nem valores de `*_env`.
- **Mesma imagem para todos os papéis:** CLI e worker Ray (trilha D). Os extras entram por `EXTRAS=ray,postgres,kafka,...`, e não há imagens divergentes entre os nós.
- **`.dockerignore`:**
  - exclui `.git`, `.venv`, `**/__pycache__`, `*.pyc`, `tests/`, `design_docs/`, `docs/`, `examples/`, `out/`, `.claude/`, `.agents/`, `.hermes/`, `*.parquet`, `*.csv`, `*.jsonl` e `.env*`;
  - `.env*` fica de fora para que segredos locais nunca entrem no contexto de build.

#### 3.12.2 Fragmentos por área (evolução sem conflito entre trilhas paralelas)

Decisão do usuário: cada trilha altera a imagem **só pelo próprio fragmento**, e nenhuma trilha edita o Dockerfile final.

- **Template:** `docker/Dockerfile.in` (DD-00) contém a imagem base e dois pontos de extensão:
  - `@fragments build`: no estágio de build, depois do `uv sync`, para passos que precisam do venv, como o preload de modelos;
  - `@fragments runtime`: no estágio final, **antes** do `USER 10001`, para criar diretórios e ajustar dono.
- **Fragmentos:** `docker/fragments/<área>.build.dockerfile` e `docker/fragments/<área>.runtime.dockerfile`.
  - As áreas são as mesmas de `examples/` (§3.2).
  - O DD-00 cria todos os fragmentos **vazios**.
  - Cada trilha só edita os seus.
- **Montagem:**
  - `scripts/render_dockerfile.py` monta o `Dockerfile` da raiz, concatenando os fragmentos numa ordem fixa de áreas: `tipos`, `relacoes`, `llm`, `execucao`, `sinks`, `schema-io`, `cli-docker`, `contrato`;
  - o `Dockerfile` gerado é versionado. O hook de pre-commit `dockerfile-render` e um teste de drift falham se ele diferir do que o script gera;
  - o script valida cada fragmento (guardrails abaixo) antes de montar.
- **Instruções permitidas em fragmentos:** `ARG`, `ENV`, `RUN`, `COPY --from=build` e `LABEL`.
- **Instruções proibidas em fragmentos:** `FROM`, `USER`, `ENTRYPOINT`, `CMD`, `EXPOSE`, `VOLUME`, `SHELL`, `HEALTHCHECK` e `ADD`.
- **Regras de conteúdo dos fragmentos:**
  - `RUN apt-get install` exige `--no-install-recommends` e limpeza de `/var/lib/apt/lists`;
  - compiladores (`gcc`, `g++`, `make`, `build-essential`) são proibidos no estágio final;
  - `ENV`/`ARG` com nome que casa com `(?i)pass|secret|token|key` só são aceitos se terminarem em `_env` (§6.5).

#### 3.12.3 Regra de evolução (vale para todos os steps do DD-00, DD-01 e DD-02)

1. **Todo step reconstrói a imagem e roda o smoke test**, mesmo sem mudar fragmentos, porque o código de `src/` entra na imagem. É o job de CI com marker `docker`, obrigatório em todo step. O smoke test base:
   - `docker run <img> --version`;
   - `id -u` = 10001;
   - `dataipsum --help`.
2. **Todo step que muda uma necessidade de runtime atualiza o fragmento da sua área.** Necessidades de runtime incluem: novo extra usado na imagem, pacote de SO, diretório gravável, variável de ambiente com padrão na imagem, asset pré-baixado ou uso alternativo do entrypoint.
3. **Todo step com mudança na imagem acrescenta testes** em `tests/docker/test_image_<área>.py`, com marker `docker`, cobrindo o que mudou. Isso inclui o smoke test funcional da área (ex.: gerar um CPF dentro do container).
4. **Toda descrição de PR tem a seção "Impacto na imagem":** fragmentos alterados, extras exigidos, variáveis novas, volumes graváveis e o tamanho medido antes/depois. Se não houve mudança, a seção diz "nenhum".
5. Cada DD/trilha tem uma subseção **"Evolução da imagem"** com o que muda na imagem naquele step.

#### 3.12.4 Evolução planejada da imagem

| Step | Mudança na imagem | Fragmento |
|---|---|---|
| **DD-00 S5** | cria a imagem base (§3.12.1), `.dockerignore`, template, fragmentos vazios, `render_dockerfile.py` e os testes base | — |
| DD-01 A (tipos) | nenhum passo novo. Os dados embarcados (`bins.yaml`, snapshot de nomes, lorem) chegam como *package data* do wheel. O smoke test gera `cpf`, `rg`, `cartao_credito` e `email` dentro do container | nenhum |
| DD-01 B (relações) | nenhum passo novo. O smoke test gera uma relação 1:N dentro do container | nenhum |
| DD-01 C (LLM) | diretório gravável de modelos, variáveis de cache e preload opcional dos pesos de toxicidade (DD-01, C.10) | `llm.build`, `llm.runtime` |
| DD-01 D (execução; Ray no M2) | telemetria do Ray desligada e uso da imagem como worker Ray (DD-01, D.10) | `execucao.runtime` |
| DD-01 S5 | o smoke test gera o schema de referência com o motor real dentro do container | — |
| DD-02 E (sinks) | nenhum pacote de SO: `psycopg[binary]`, PyMySQL e `confluent-kafka` usam wheels. O teste constrói com `EXTRAS=postgres,mysql,kafka` sem compilador (DD-02, E.10) | nenhum |
| DD-02 F (import/export) | nenhum passo novo. O smoke test roda `schema export` dentro do container | nenhum |
| DD-02 G (CLI) | a CLI completa substitui o esqueleto; o `ENTRYPOINT` não muda. O compose de dev (trilha G) usa esta imagem | nenhum |
| DD-02 H (contrato) | nenhum passo novo. O smoke test roda `schema jsonschema` dentro do container | nenhum |
| DD-02 S5 | ponta a ponta via compose (trilha G) | — |

## 4. Armazenamento de dados

- **Arquivos de saída:** trilha E.
- **Manifesto:** §3.7.
- **Cache LLM:** trilha C, em `<cache_dir>`, com padrão `<out>/_cache/llm`.
- **Schemas emitidos:** `<out>/_schema/`.

Nenhum outro estado persistente.

## 5. Alternativas descartadas

- **Schema em TOML ou DSL Python:** o YAML é o contrato da UI e o que o RESEARCH decidiu.
- **Registry por import-time side effect:** é frágil e não controla plugins. Foi trocado por um `register()` explícito com allowlist.
- **Manifesto em SQLite:** seria mais robusto para concorrência, mas é menos legível e desnecessário com um único escritor (o driver).
- **Seeds só por chunk (PRNG sequencial):** ver o trade-off em §3.6.

## 6. Guardrails e validações de segurança

1. **YAML seguro:**
   - só `yaml.safe_load` com loader customizado que **rejeita âncoras e aliases** (proteção contra *billion laughs*) e tags customizadas;
   - arquivo ≤ 1 MiB;
   - profundidade ≤ 20;
   - ≤ 200 tabelas, ≤ 500 colunas por tabela e `params` ≤ 64 KiB serializados.
2. **Identificadores:**
   - `name` de schema, tabela e coluna precisa casar com `^[a-z_][a-z0-9_]{0,62}$`;
   - palavras reservadas SQL são permitidas, mas os exportadores e sinks sempre as quotam;
   - isso impede path traversal em nomes de arquivo e injeção em DDL/COPY.
3. **Limites de volume:**
   - a soma das linhas planejadas é ≤ `limits.max_rows_total`, com padrão 1e8, e o `--max-rows` da CLI pode reduzir ou elevar esse valor;
   - se passar, `ResourceLimitError` antes de gerar qualquer dado.
4. **Diretório de saída:**
   - é resolvido com `Path.resolve()`;
   - todo arquivo escrito precisa estar dentro dele, e a verificação acontece em `manifest.py` e é reusada pelos sinks;
   - symlinks dentro de `<out>` são recusados;
   - `generate` exige `<out>` inexistente ou vazio. Qualquer `<out>` não vazio gera `OutputDirError`, **inclusive se já contiver um `_manifest.json`** (decisão do usuário). Nesse caso a mensagem indica `dataipsum resume <out>` para retomar, ou um novo diretório para gerar de novo. `generate` nunca sobrescreve nem mistura execuções.
5. **Segredos:**
   - o schema **não aceita** campos `api_key`, `password` ou `token`, e o erro de validação sugere `*_env`;
   - o manifesto grava só `api_key_env` (o nome), nunca o valor;
   - opções de sink passam por um sanitizador antes de ir para o manifesto e os logs. Ele remove chaves que casam com `(?i)pass|secret|token|key`, **exceto as terminadas em `_env`** (`password_env`, `dsn_env`, `sasl_password_env`, `api_key_env`...). Essas guardam só o **nome** da variável de ambiente, que é seguro e necessário para o `resume` reconectar. O valor da variável nunca é lido para dentro do manifesto;
   - a mesma regra de exceção `_env` vale para a validação de `--sink-opt` na CLI (DD-02, G.5).
6. **Plugins:** allowlist obrigatória (§3.4); nenhum plugin é carregado por padrão; todo plugin carregado é logado.
7. **Determinismo como guardrail:** o teste de arquitetura proíbe fontes de aleatoriedade fora de `seeds.py` (§3.6).
8. **Contratos congelados:** mudanças em `contracts/`, `pyproject.toml` ou `uv.lock` depois do merge exigem PR de "mudança de contrato".
9. **Tipagem e lint:** `mypy --strict` sem `type: ignore` fora de stubs de terceiros, e sem `ruff` suprimido em massa.
10. **Padrões de código** (§3.10): as regras `C4`, `PERF`, `SIM`, `FURB`, `N`, `E741`, `ERA` e `RET` do ruff não podem ser desligadas globalmente; `# noqa` exige justificativa na linha.
11. **Pre-commit e segurança** (§3.2.1): SAST (bandit, semgrep OWASP), SCA (pip-audit, OWASP Dependency-Check), detecção de segredos (gitleaks) e lint de Dockerfile (hadolint) são obrigatórios. Exceções só com justificativa e data de expiração.
12. **Imagem Docker** (§3.12):
    - não-root (10001) e sem compiladores;
    - base e `uv` com versão fixa;
    - sem segredos embutidos;
    - fragmentos validados (instruções proibidas, `apt-get` seguro, sem `ENV` de segredo);
    - `Dockerfile` sempre gerado;
    - `hadolint` e `trivy` obrigatórios.

## 7. Plano de implementação

O DD-00 tem 5 steps. O **S1 vem primeiro**; **S2, S3, S4 e S5 rodam em paralelo** depois do S1.

| Step | Conteúdo | Depende de | Arquivos |
|---|---|---|---|
| **S1 — Esqueleto, tooling e contratos** | `pyproject.toml` com todas as deps/extras/entry points e o ruff configurado com as regras da §3.10; `.pre-commit-config.yaml` com todos os hooks da §3.2.1, `security/exceptions.yaml` vazio e o script que o valida; `uv.lock`; pre-commit; `.gitignore`; árvore de pacotes com `register()` vazios; `contracts/*` (Protocols + dataclasses); `errors.py`; `registry.py` (built-ins, allowlist, conflitos); remoção de `data_ipsum.py`; README atualizado; confirmação da ausência de `study/` | — | raiz, `contracts/`, `errors.py`, `registry.py` |
| **S2 — Modelo de schema** | `schema/models.py`, `loader.py` (limites, safe_load sem aliases, validação em camadas), `inline.py` (`build_inline_schema`), `jsonschema.py`, `config.py` (`RunOptions`, env, precedência) | S1 | `schema/`, `config.py` |
| **S3 — Seeds e Draws** | `seeds.py` (derive, mix, draw_u64, `Draws` vetorizado, slots reservados); teste de arquitetura anti-aleatoriedade | S1 | `seeds.py`, `tests/core/` |
| **S4 — Manifesto, façade e fakes** | `manifest.py` (atômico, flush em lote, confinamento de caminho, sanitizador); `api.py` com esqueletos; `testing/fakes.py` + `SchemaBuilder` | S1 | `manifest.py`, `api.py`, `testing/` |
| **S5 — Imagem Docker base** | `docker/Dockerfile.in`, fragmentos vazios de todas as áreas, `scripts/render_dockerfile.py` (montagem + validação dos fragmentos), `Dockerfile` gerado, `.dockerignore`, job de CI `docker` e `tests/docker/test_image_base.py` (§3.12) | S1 | `docker/`, `scripts/`, `Dockerfile`, `.dockerignore`, `tests/docker/` |

Cada step entrega também os testes unitários da §7.1 referentes aos seus módulos e os exemplos da §7.2 referentes às features que implementa.

### 7.1 Testes unitários (obrigatórios, em `tests/core/unit/`)

| Módulo | Testes mínimos |
|---|---|
| `registry.py` | registra e obtém built-in; nome desconhecido gera erro com sugestão; plugin sem allowlist é ignorado e avisado; plugin na allowlist é carregado; `*` libera todos; `--no-plugins` sobrepõe a env; conflito plugin × built-in e plugin × plugin gera `RegistryConflictError` (entry points simulados com `importlib.metadata` mockado) |
| `schema/loader.py` | YAML válido mínimo e completo (§3.3); rejeita âncora/alias, tag customizada, arquivo > 1 MiB, profundidade > 20, 201 tabelas, 501 colunas, `params` > 64 KiB; `version` ≠ 1; erros acumulados por camada com caminho correto; padrões aplicados (`locale`, `chunk_size`, `null_ratio`) |
| `schema/models.py` | colunas implícitas de tabela via `Planner.implied_columns` (com FakePlanner) e colisão com colunas do usuário; `depends_on` com ciclo ou apontando para coluna `llm_*` ⇒ erro; identificador válido/inválido (`Usuarios`, `../x`, `1col`, 64 chars); `rows` × `rows_from` mutuamente exclusivos; `null_ratio`/`invalid_ratio` fora de [0,1]; `invalid_ratio` sem `supports_invalid`; `format` sem `supports_format`; `max_length` ausente em `string`; campos proibidos `api_key`/`password`/`token`; nomes implícitos (`is_offensive`, `is_placeholder`) declarados pelo usuário geram erro; normalização acrescenta `implied_columns` ao fim |
| `schema/inline.py` | `id:int:pk`, `nome:nome_proprio`, `bio:string:max_length=50`; tipo inexistente; chave de parâmetro inválida; mais de uma coluna `pk` |
| `schema/jsonschema.py` | o JSON Schema gerado valida o exemplo §3.3 e rejeita erros estruturais; é determinístico (duas gerações idênticas) |
| `config.py` | precedência CLI > env > schema > padrão; faixas de `cpu_max`/`mem_max`; `DATAIPSUM_PLUGINS` parseada |
| `seeds.py` | golden values de `derive`, `mix` e `draw_u64` (vetores fixados); `uniform` em [0,1); `integers` respeita limites inclusive/exclusivo e faixas > 2^53; `Draws` com índices não contíguos = lote contíguo; independência de `chunk_size`; slots 0 e 1 reservados; `normal` com média/desvio esperados (tolerância); `seed_llm` estável |
| teste de arquitetura | falha com `import random`, `from random`, `np.random.` fora de `seeds.py` |
| `manifest.py` | round-trip; escrita atômica sob falha simulada antes do `os.replace`; flush em lote (50 chunks / 5 s, com relógio falso); confinamento de caminho (`../`, symlink); sanitizador remove `password`, `secret`, `token` e `*key*` e **preserva** `password_env`, `dsn_env`, `sasl_password_env` e `api_key_env` (só o nome da variável; o valor nunca aparece); `ManifestMismatchError` por hash de schema e por versão major |
| `api.py` | cada função delega ao módulo da trilha; `NotImplementedError` com o nome da trilha enquanto ela não existir; `generate` recusa `<out>` não vazio **com ou sem** manifesto, e a mensagem sugere `resume` quando há manifesto; `<out>` inexistente ou vazio é aceito |
| padrões de código | `tests/core/unit/test_code_standards.py` roda o ruff do projeto sobre fixtures em `tests/core/fixtures/code_standards/`: um laço `for` com `append` (espera `PERF401`), código comentado (`ERA001`), variável `l` (`E741`) e função `processData` (`N802`) são reprovados; a versão funcional e bem nomeada equivalente passa; o `pyproject.toml` não desliga nenhuma das regras da §3.10 |
| pre-commit e segurança | `test_precommit_config.py`: `.pre-commit-config.yaml` contém os hooks da §3.2.1 nos estágios certos, com `rev` fixo nos hooks de terceiros e `uv run` nos locais; o validador de `security/exceptions.yaml` rejeita entrada sem justificativa, sem responsável ou com data vencida; `# nosec`/`# nosemgrep` sem exceção registrada é detectado; fixtures com vulnerabilidade conhecida (ex.: `subprocess(..., shell=True)` com entrada externa, `yaml.load` sem `SafeLoader`) são reprovadas por bandit/semgrep |
| imagem (`render_dockerfile.py`) | monta na ordem fixa de áreas; fragmento com `FROM`, `USER`, `ENTRYPOINT`, `CMD`, `EXPOSE`, `VOLUME`, `SHELL`, `HEALTHCHECK` ou `ADD` é rejeitado; `apt-get install` sem `--no-install-recommends` ou sem limpeza é rejeitado; compilador no estágio final é rejeitado; `ENV API_KEY=...` rejeitado e `ENV X_API_KEY_ENV=...` aceito; `--check` detecta `Dockerfile` divergente; fragmentos vazios geram exatamente a imagem base |
| imagem (marker `docker`, `tests/docker/test_image_base.py`) | constrói com `EXTRAS=""` e com `EXTRAS=all`; `--version` e `--help` funcionam; `id -u` = 10001; nenhum `gcc`/`cc`/`make` na imagem; `.env` de teste no contexto não entra na imagem; `hadolint` sem avisos; `trivy` sem `HIGH`/`CRITICAL` corrigíveis; label de versão presente; tamanho medido e registrado (meta a definir pelo usuário) |
| `testing/fakes.py` | FakeSink guarda batches e falha no chunk N; FakeLLM roteirizado e com falhas; FakeExecutor em série; SchemaBuilder produz um schema válido |

### 7.2 Exemplos de features opcionais (em `examples/core/`)

| Arquivo | Demonstra |
|---|---|
| `examples/core/seed-fixa.yaml` | `seed` explícita: duas execuções produzem saída idêntica |
| `examples/core/sem-seed.yaml` | seed ausente, sorteada e registrada no manifesto |
| `examples/core/limites.yaml` | `limits.max_rows_total` e `chunk_size` customizados |
| `examples/core/plugin/` | pacote mínimo de plugin (gerador `exemplo_placa`) com entry point, e o uso de `DATAIPSUM_PLUGINS` |
| `examples/core/docker/basico.sh` | `docker build` + `docker run -v ./examples:/schemas:ro -v ./out:/out <img> gen ...` |
| `examples/core/docker/extras.sh` | `--build-arg EXTRAS=ray,postgres,kafka` e a mesma imagem como worker Ray (`--entrypoint ray`) |
| `examples/core/docker/fragmento.md` | como uma área adiciona um fragmento, roda `render_dockerfile.py` e escreve o teste `test_image_<área>.py` |
| `examples/core/README.md` | explica cada exemplo, o comando para executá-lo e o resultado esperado |

## 8. Critérios de aceitação

1. `uv sync --frozen` instala a base; `uv sync --all-extras` instala tudo; os 4 quality gates passam no repositório vazio de lógica.
2. `data_ipsum.py` não existe mais, e `study/` continua inexistente (verificado).
3. `pip install .` sem extras **não** instala `ray`, `psycopg`, `PyMySQL`, `confluent-kafka`, `detoxify`, `torch` nem `anthropic`.
4. `dataipsum --help` executa. Ele pode só listar comandos que levantam `NotImplementedError` com uma mensagem clara.
5. O YAML de exemplo da §3.3 carrega sem erros quando os tipos estão registrados (em teste, com geradores fake).
6. YAML com alias/âncora, arquivo > 1 MiB, 201 tabelas, identificador `../x` ou `Usuarios`, campo `api_key` e `rows` junto com `rows_from`: cada um produz `SchemaError` com o caminho correto.
7. `invalid_ratio` em um tipo sem `supports_invalid` gera `SchemaError` no caminho da coluna.
8. `derive` e `draw_u64` batem com os vetores de teste fixados no repositório (golden values), e o resultado é idêntico entre execuções, processos e máquinas.
9. `Draws` para as linhas `[5, 1_000_000, 42]` retorna os mesmos valores que os índices individuais extraídos de lotes contíguos (acesso aleatório O(1)).
10. `uniform` está em `[0,1)`; teste qui-quadrado com 10^6 amostras e 100 bins com p > 0.001 (marcado `slow`).
11. O teste de arquitetura falha se um arquivo em `src/dataipsum/` (exceto `seeds.py`) contiver `import random`, `from random` ou `np.random.`.
12. O manifesto sobrevive a um `kill -9` simulado entre o tmp e o replace: o arquivo anterior continua válido e parseável.
13. Nenhum valor de variável de ambiente usada como `api_key_env` aparece no manifesto ou nos logs (teste com a variável contendo `SEGREDO123`).
14. Plugin externo sem allowlist não é carregado e emite um aviso. Com allowlist, é carregado. Plugin com nome de built-in gera `RegistryConflictError`.
15. Um escritor de arquivo fora de `<out>` (via `../` ou symlink) gera `OutputDirError`.
16. O JSON Schema exportado valida o YAML de exemplo e rejeita os casos do item 6 que são estruturais.
17. Cada linha da tabela §7.1 tem ao menos um teste correspondente em `tests/core/unit/`, e todos passam sem rede nem Docker.
18. Os arquivos da §7.2 existem. Cada YAML passa em `dataipsum.validate`, e `examples/core/README.md` descreve comando e saída esperada de cada um.
19. `generate` em um `<out>` que já contém `_manifest.json` gera `OutputDirError` sem tocar em nenhum arquivo, e a mensagem sugere `dataipsum resume <out>`.
20. O manifesto de uma execução com `--sink-opt password_env=PG_PASS` contém `password_env: PG_PASS` e **não** contém o valor de `PG_PASS`. Uma opção `password` (sem `_env`) nunca aparece.
21. A normalização de uma tabela `thread` acrescenta, via `Planner.implied_columns`, as colunas `seq`, `autor`, `timestamp`, `texto`, `is_offensive` e `is_placeholder` ao fim. Declará-las manualmente gera `SchemaError`.
22. O ruff do projeto habilita `C4`, `PERF`, `SIM`, `FURB`, `N`, `E741`, `ERA` e `RET` sem exclusões globais, e reprova as fixtures de violação da §7.1.
23. O código do DD-00 segue a §3.10: sem `for` com acumulador fora das exceções listadas, sem nomes genéricos (`data`, `tmp`, `res`, `process`) e sem comentários que repitam o código. Isso é verificado pelo agente de revisão do step.
24. `uv run pre-commit install --hook-type pre-commit --hook-type pre-push` instala os hooks, e um commit com teste quebrado, erro de tipo, achado do bandit/semgrep, dependência com CVE conhecida ou segredo no diff é **bloqueado**.
25. `pre-commit run --all-files` passa no repositório do S1, e a CI roda o mesmo comando mais os hooks de `pre-push`.
26. OWASP Dependency-Check roda no `pre-push` e na CI e falha com CVSS ≥ 7.0. Com `NVD_API_KEY` ausente, o hook falha com uma mensagem que explica como configurar a chave; ele nunca passa em silêncio.
27. Toda exceção de segurança está em `security/exceptions.yaml` com justificativa, responsável e expiração. Uma exceção vencida reprova o hook.
28. O S5 entrega uma imagem que constrói com `EXTRAS` vazio e com `EXTRAS=all`, roda como UID 10001, não contém compilador e responde `dataipsum --version`.
29. O `Dockerfile` da raiz é exatamente a saída de `render_dockerfile.py`. Editá-lo à mão ou incluir instrução proibida num fragmento reprova o pre-commit e a CI.
30. Todo step do DD-00, do DD-01 e do DD-02 executa o job de CI `docker` (build + smoke), e cada step com mudança de runtime acrescenta `tests/docker/test_image_<área>.py` e atualiza só o fragmento da própria área.

### BDD

```gherkin
# language: pt
Funcionalidade: Fundação e contratos do dataIpsum

  Cenário: Carregar um schema válido
    Dado o arquivo "examples/loja.yaml" com version 1 e três tabelas
    Quando eu chamo load_schema no arquivo
    Então recebo um Schema com as tabelas "usuarios", "produtos" e "pedidos"
    E o locale efetivo de "usuarios.nome" é "pt_BR"

  Cenário: Rejeitar YAML com âncoras
    Dado um schema YAML que usa "&base" e "*base"
    Quando eu chamo load_schema
    Então recebo SchemaError mencionando "âncoras/aliases não são permitidos"

  Cenário: Rejeitar segredo em texto claro
    Dado um provedor LLM com o campo "api_key: sk-123"
    Quando eu valido o schema
    Então recebo SchemaError no caminho "llm.providers.nuvem.api_key"
    E a mensagem sugere usar "api_key_env"
    E a mensagem não contém "sk-123"

  Cenário: invalid_ratio em tipo sem regra
    Dado a coluna "nome" do tipo "nome_proprio" com invalid_ratio 0.1
    Quando eu valido o schema
    Então recebo SchemaError no caminho "tables[0].columns[1].invalid_ratio"

  Cenário: Seed sorteada quando ausente
    Dado um schema sem o campo seed
    Quando eu executo generate com FakeExecutor e FakeSink
    Então o manifesto contém "seed_source": "random" e um seed entre 0 e 2^63-1

  Cenário: Sorteio independente do tamanho do chunk
    Dado seed 42 e a coluna "usuarios.cpf"
    Quando eu gero Draws para as linhas 0..9999 em um lote
    E gero Draws para as mesmas linhas em lotes de 1000
    Então os arrays resultantes são idênticos

  Cenário: Recalcular uma linha isolada
    Dado seed 42
    Quando eu calculo draws.uniform(slot=2) apenas para a linha 777
    Então o valor é igual ao da posição 777 do lote 0..9999

  Cenário: Plugin não autorizado
    Dado um pacote instalado que registra o gerador "cnpj" via entry point
    E a variável DATAIPSUM_PLUGINS não está definida
    Quando o registry é inicializado
    Então "cnpj" não está registrado
    E um aviso informa como autorizar o plugin

  Cenário: Diretório com execução anterior
    Dado o diretório "out" com um "_manifest.json" de uma execução anterior
    Quando eu executo generate com saída "out"
    Então recebo OutputDirError sugerindo "dataipsum resume out"
    E nenhum arquivo de "out" é alterado

  Cenário: Nome de variável de ambiente preservado no manifesto
    Dado o sink postgres com a opção "password_env" igual a "PG_PASS" e PG_PASS contendo "SEGREDO123"
    Quando a execução grava o manifesto
    Então o manifesto contém "password_env": "PG_PASS"
    E o manifesto não contém "SEGREDO123"

  Cenário: Pre-commit bloqueia vulnerabilidade
    Dado os hooks de pre-commit instalados
    E um arquivo em "src/" que chama "yaml.load" sem SafeLoader
    Quando eu tento fazer commit
    Então o commit é bloqueado pelo hook "bandit" ou "semgrep"

  Cenário: Pre-commit bloqueia dependência vulnerável
    Dado uma dependência com CVE conhecida adicionada ao uv.lock
    Quando eu tento fazer commit
    Então o commit é bloqueado pelo hook "pip-audit"

  Cenário: Pre-commit bloqueia teste quebrado
    Dado um teste unitário que falha
    Quando eu tento fazer commit
    Então o commit é bloqueado pelo hook "pytest-unit"

  Cenário: Imagem base não-root
    Dado a imagem construída com EXTRAS vazio
    Quando eu executo "docker run --entrypoint id <imagem> -u"
    Então a saída é "10001"

  Cenário: Fragmento com instrução proibida
    Dado o fragmento "docker/fragments/llm.runtime.dockerfile" contendo "USER root"
    Quando eu executo "scripts/render_dockerfile.py --check"
    Então o script falha informando que "USER" não é permitido em fragmentos

  Cenário: Dockerfile editado à mão
    Dado o "Dockerfile" da raiz alterado manualmente
    Quando o hook "dockerfile-render" roda
    Então o commit é bloqueado com a instrução de rodar "render_dockerfile.py"

  Cenário: Manifesto atômico
    Dado um manifesto existente e válido
    Quando a escrita do novo manifesto é interrompida antes do rename
    Então o manifesto em disco é o anterior e é JSON válido
```

## 9. Rastreabilidade (RESEARCH → este doc)

| RESEARCH | Onde |
|---|---|
| §2.1 Python 3.12+, reescrita do zero | §3.1, §3.2, S1 |
| §2.1 biblioteca importável + CLI fina | §3.8 (façade); CLI na trilha G |
| §2.1 uv, src layout, pytest, ruff, mypy | §3.2 |
| §2.1 extras `[ray]`, `[postgres]`, `[mysql]`, `[kafka]` | §3.2 |
| §2.2 YAML validado por Pydantic/JSON Schema; flags inline; contrato da UI | §3.3 |
| §2.4 registry único + entry points; built-ins registrados nele | §3.4 |
| §2.4 `null_ratio` padrão 0 em toda coluna | §3.3, §3.6 (slot 0) |
| §2.5 seed opcional, sorteada e registrada; derivação tabela → coluna → chunk | §3.6, §3.7 |
| §2.8 manifesto (seed, schema, chunks concluídos/pendentes) | §3.7 |
| §3 M1: remover `data_ipsum.py` e `study/` | §3.1, S1 |
| §2.9 imagem multi-stage, `uv.lock`, `python:3.12-slim`, só o venv | §3.12.1, S5 |
| §2.9 não-root, `ENTRYPOINT ["dataipsum"]` | §3.12.1 |
| §2.9 `EXTRAS` por build arg; mesma imagem como worker Ray | §3.12.1 (worker: DD-01, D.10) |
| §2.9 volumes de schema/saída; configuração do LLM por env | §3.12.1 (LLM: DD-01, C.10) |
| §2.9 `.dockerignore` | §3.12.1 |
| §4 definir o formato exato do YAML | §3.3 (**proposta, para revisão**) |

## 10. Questões em aberto e riscos

- **Trade-off (§3.12.2):** fragmentos por área evitam conflitos entre trilhas paralelas no Dockerfile, ao custo de um passo de geração (`render_dockerfile.py`) e de um teste de drift.
- **Risco:** construir a imagem em todo step deixa a CI mais lenta. A mitigação é o cache de camadas (`pyproject.toml`/`uv.lock` copiados antes de `src/`).
- **Para revisão (§3.2.1):** a escolha das ferramentas:
  - SAST: bandit + semgrep com `p/owasp-top-ten`;
  - SCA: pip-audit + OWASP Dependency-Check;
  - segredos: gitleaks;
  - Dockerfile: hadolint;
  - imagem: trivy.
  Também os limiares (bandit ≥ média, CVSS ≥ 7.0, trivy HIGH/CRITICAL) e a divisão entre `pre-commit` e `pre-push`.
- **Risco:** o semgrep baixa as regras `p/owasp-top-ten` do registry e o Dependency-Check baixa a base NVD, ambos por rede e o segundo com `NVD_API_KEY`. Em ambiente offline, os dois hooks falham de forma explícita em vez de passar.
- **Risco:** rodar os testes unitários e o mypy em todo commit deixa o commit mais lento. A mitigação é manter os unitários sem rede e sem Docker (§3.2).
- **Trade-off (§3.10):** em dados em volume, a vetorização numpy/pyarrow tem prioridade sobre `map`/`filter`/`reduce` em Python, porque a regra funcional não pode custar o desempenho exigido pelo DD-01.
- **Para revisão:** o formato do YAML (§3.3), principalmente os nomes `rows_from`/`via`/`pair`, o `chunk_size` padrão de 10000 e o limite padrão de 1e8 linhas.
- **Risco:** `detoxify`/`torch` deixam a imagem Docker bem maior quando `EXTRAS` inclui `toxicity` (evolução pelo fragmento `llm` do DD-01, C.10). Por isso a imagem de `EXTRAS` vazio nunca inclui `torch`.
- **Risco:** congelar os contratos cedo pode forçar PRs de "mudança de contrato". A mitigação é revisar este doc com as 8 trilhas antes do merge do S1.
