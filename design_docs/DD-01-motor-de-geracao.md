# DD-01 — Motor de geração

| | |
|---|---|
| **Status** | Proposto (para revisão) |
| **Marcos** | M1 (trilhas A, B, C e a parte local de D) · M2 (Ray, na trilha D) |
| **Onda** | 1. Começa depois do merge do [DD-00](DD-00-fundacao-e-contratos.md) |
| **Fonte** | `RESEARCH.md` §1, §2.4, §2.5, §2.6, §2.7, §3 (M1, M2) e §4 |
| **Docs relacionados** | [DD-00 — Fundação e contratos](DD-00-fundacao-e-contratos.md) · [DD-02 — Saídas, interfaces e entrega](DD-02-saidas-interfaces-e-entrega.md) |

---

## 0. Paralelização e integração

Este documento agrupa **quatro trilhas que são implementadas em paralelo**. Elas eram quatro design docs separados e foram agrupadas aqui por decisão de projeto. Cada trilha:

- depende **somente** dos contratos, `Draws`, registry e fakes do DD-00;
- escreve **somente** nos próprios diretórios;
- tem design, guardrails, testes unitários, exemplos, critérios de aceitação e BDD próprios;
- corresponde a **um step** do `/task-creator`. O step 5 é a integração.

| Trilha | Escopo | Diretórios exclusivos | Step |
|---|---|---|---|
| **A** | Tipos primitivos e campos com regra | `src/dataipsum/types/`, `tests/types/`, `examples/tipos/`, `docker/fragments/tipos.*`, `tests/docker/test_image_tipos.py` | S1 |
| **B** | Relações, chaves e determinismo | `src/dataipsum/relations/`, `tests/relations/`, `examples/relacoes/`, `docker/fragments/relacoes.*`, `tests/docker/test_image_relacoes.py` | S2 |
| **C** | Campos gerados por LLM | `src/dataipsum/llm/`, `tests/llm/`, `examples/llm/`, `docker/fragments/llm.*`, `tests/docker/test_image_llm.py` | S3 |
| **D** | Execução, paralelismo e recursos | `src/dataipsum/execution/`, `tests/execution/`, `examples/execucao/`, `docker/fragments/execucao.*`, `tests/docker/test_image_execucao.py` | S4 |
| — | Integração ponta a ponta do motor | `tests/integration/motor/` | S5 (depende de S1–S4) |

**Regras de paralelismo:**
- S1, S2, S3 e S4 **começam juntos** e não esperam uns pelos outros.
- Quando uma trilha precisa de outra, usa o contrato do DD-00 e testa contra um fake:
  - D usa `FakePlanner` e geradores fake;
  - C usa `FakeLLM` e o `GenContext` do DD-00;
  - B usa geradores fake para `row_at`.
- **Imagem Docker:** cada trilha evolui a imagem **só pelo próprio fragmento** (`docker/fragments/<área>.*`) e pelos próprios testes de imagem (DD-00 §3.12). Nenhuma trilha edita o `Dockerfile`, que é gerado. Cada trilha tem uma subseção "Evolução da imagem" (A.10, B.10, C.10, D.10).
- Nenhuma trilha edita `pyproject.toml`, `uv.lock` ou `contracts/`. Se precisar, abre um PR de "mudança de contrato" (DD-00 §3.1).
- O **S5** é o único step encadeado: roda depois de S1–S4 e troca os fakes pelas implementações reais. Ele usa `FakeSink` e `FakeLLM`, então **não** depende do DD-02.

As trilhas do DD-02 (E–H) também rodam em paralelo com estas.

## 1. Contexto e escopo

O motor transforma um `Schema` validado (DD-00 §3.3) em chunks de dados (`pyarrow.RecordBatch`) entregues a um `Sink`. Ele cobre:

- os geradores de valores (A);
- como as tabelas se relacionam e quantas linhas cada uma tem (B);
- o texto produzido por LLM (C);
- como tudo isso é distribuído entre processos e nós, respeitando os recursos da máquina (D).

## 2. Objetivos e não-objetivos (do documento)

**Objetivos**
- Todos os tipos do RESEARCH §2.4, válidos por padrão e com inválidos controlados.
- Relações 1:1, 1:N, N:N e threads, com FK e cardinalidade **sem consultar dados gerados**.
- Campos LLM coerentes com o resto da linha, com toxicidade controlada, modos `unique` e `pool`, cache e tolerância a falha.
- Geração em streaming por chunks, local ou distribuída (Ray), com a concorrência adaptada à carga real da máquina.

**Não-objetivos**
- Auto-relacionamentos (hierarquias na mesma tabela) e ciclos entre tabelas: são erro de validação.
- Distribuições estatísticas arbitrárias por coluna além das listadas em cada tipo.
- Reprodutibilidade exata de texto LLM: é só melhor esforço (RESEARCH §4).
- Referências multi-hop em templates (`{a.b.c}`): só um nível.
- Compartilhar o cache LLM entre nós Ray: cada nó tem o seu, a menos que `cache_dir` esteja em um FS compartilhado.

---

## Trilha A — Tipos primitivos e campos com regra (S1)

### A.1 Contexto e escopo

A trilha A implementa e registra (via `types.register(registry)`) os geradores determinísticos:
- **primitivos:** String, Char, Date, Timestamp, Int, Float, Boolean, UUID, Decimal, Time, JSON e Array;
- **campos com regra:** CPF, RG, cartão de crédito, nome próprio e **endereço de e-mail** (`email`, decisão do usuário).

Também implementa o registry de **locales**.

### A.2 Objetivos / Não-objetivos

- **Objetivo:** todo gerador é vetorizado, determinístico via `Draws` e declara um `LogicalType` exato.
- **Objetivo:** campos com regra são válidos por padrão. `invalid_ratio` produz inválidos **garantidamente** inválidos.
- **Não-objetivo:** CNPJ, placa etc. Ficam como exemplos de plugin.
- **Distinção (decisão do usuário):** `email` é o **endereço** (trilha A, gerador com regra). O **corpo** de um e-mail é o template LLM `llm_email` (trilha C).
- **Não-objetivo:** RG de outras UFs neste marco. A arquitetura permite adicioná-las como variantes via registry.

### A.3 Design

**Princípios comuns**
- `generate(column, batch, draws, ctx)` devolve `pyarrow.Array` com `len(batch.rows)` valores. **Não** produz nulos, porque o motor aplica `null_ratio` com o slot 0.
- Toda aleatoriedade vem de `draws` (slots ≥ 2). O slot 1 (`invalid_mask`) é entregue pronto em `batch.invalid_mask`.
- `validate_params` rejeita parâmetros desconhecidos, porque um erro de digitação não pode passar em silêncio.
- **Padrões fixos, nunca relativos a "hoje":** um padrão relativo à data corrente quebraria o determinismo.

**Primitivos**

| Tipo | Parâmetros (padrão) | Valor gerado | `LogicalType` |
|---|---|---|---|
| `string` | `max_length` **obrigatório** (N ≥ 1); `min_length` (0); `charset`: `alpha` \| `alnum` \| `lorem` (`alpha`) | comprimento uniforme em [min_length, N]; `lorem` usa palavras pt-BR de lista embarcada, cortadas em N | `string(N)` |
| `char` | `length` (1), 1..255; `charset` como acima | comprimento fixo | `char(length)` |
| `int` | `min` (0), `max` (2^31−1), inclusivos | uniforme inteiro | `int32` se [min,max] cabe em int32, senão `int64` |
| `float` | `min` (0.0), `max` (1.0); `decimals` (opcional, 0..15) | uniforme; arredondado se `decimals` | `float64` |
| `decimal` | `precision` (10), 1..38; `scale` (2), 0..precision; `min`/`max` como **strings** | sorteia o valor não escalado inteiro em [min·10^s, max·10^s], então é exato | `decimal(p,s)` |
| `boolean` | `true_ratio` (0.5) | `uniform < true_ratio` | `boolean` |
| `date` | `min` (`2000-01-01`), `max` (`2030-12-31`) | dia uniforme | `date` |
| `time` | `min` (`00:00:00`), `max` (`23:59:59`); `precision`: `s` \| `ms` (`s`) | uniforme | `time` |
| `timestamp` | `min` (`2000-01-01T00:00:00Z`), `max` (`2030-12-31T23:59:59Z`); `timezone` (false) | uniforme em milissegundos | `timestamp(tz)` |
| `uuid` | — | 128 bits de dois slots, com bits de versão 4 e variante RFC 4122 | `uuid` |
| `json` | `fields`: mapa nome → `{type, params}` de primitivos (1..50 campos); `max_depth` (3) | objeto JSON serializado (texto UTF-8, chaves em ordem declarada) | `json` |
| `array` | `items: {type, params}` (primitivo); `min_items` (0), `max_items` (10, ≤ 1000) | lista | `array(item, max_items)` |

**Campos com regra**

| Tipo | Regra de validade | `invalid_ratio` produz | `format` (padrão `masked`) | `LogicalType` |
|---|---|---|---|---|
| `cpf` | 9 dígitos-base, **sem** base de dígitos todos iguais. DV1 e DV2 por mod 11: pesos 10..2 e depois 11..2; resto < 2 ⇒ 0, senão 11 − resto | DV2 trocado por `(DV2 + 1 + k) mod 10`, k ∈ [0,8] via draw. Garante DV errado | `masked` `123.456.789-09`; `unmasked` `12345678909` | `char(14)` / `char(11)` |
| `rg` | **padrão SP**: 8 dígitos d1..d8; `soma = Σ dᵢ·(i+1)` (pesos 2..9); `DV = (11 − soma mod 11) mod 11`; DV 10 ⇒ `X`. Verificação equivalente: `soma + 100·DV ≡ 0 (mod 11)` | DV trocado por outro valor de {0..9, X} ≠ correto | `masked` `12.345.678-2`; `unmasked` `123456782` | `char(12)` / `char(9)` |
| `cartao_credito` | prefixo BIN da bandeira + dígitos aleatórios + **DV Luhn** | último dígito trocado, o que garante falha de Luhn | `masked`: grupos 4-4-4-4 (Amex 4-6-5) separados por espaço; `unmasked`: só dígitos | `string(19)` / `string(16)` |
| `nome_proprio` | nome + 1 ou 2 sobrenomes de listas pt_BR embarcadas; `params.gender`: `any` \| `f` \| `m`; `params.parts`: `first` \| `full` (`full`) | **não suporta** (`supports_invalid = False`, conforme decisão) | não suporta | `string(max_length)`, padrão 120 |
| `email` | endereço sintaticamente válido (subconjunto seguro da RFC 5322, detalhado abaixo), com domínio de `params.domains` | variante malformada sorteada, que garante falha em `is_valid_email` | não suporta | `string(max_length)`; padrão e teto 254 |

- **Bandeiras e BINs** ficam em `types/data/bins.yaml`, embarcado e **para revisão**. O usuário restringe a lista por `params.brands` e informa BINs extras em `params.extra_bins: [{brand, prefix, length}]`.

  | Bandeira | Prefixos padrão | Comprimento |
  |---|---|---|
  | `visa` | 4 | 16 |
  | `mastercard` | 51–55, 2221–2720 | 16 |
  | `amex` | 34, 37 | 15 |
  | `elo` | 636368, 636297, 504175, 438935, 451416, 627780 | 16 |
  | `hipercard` | 606282 | 16 |

  - A bandeira é sorteada uniformemente entre as permitidas. `params.weights` permite ponderar.
- **Nome próprio:** as listas vêm de um *snapshot* versionado em `types/data/names_pt_BR.json`, extraído dos providers do Faker em tempo de desenvolvimento. O snapshot **não** depende da versão do Faker instalada, então a atualização do Faker não muda os dados. Um `max_length` menor que o nome sorteado faz o gerador tentar até 8 slots extras; se nenhum couber, trunca na fronteira de palavra.
- **Endereço de e-mail (`email`)** (decisões do usuário: endereço válido, `invalid_ratio` suportado, domínios reservados por padrão, nome da linha e opção `unique`):
  - **Parâmetros:**
    - `domains`: padrão `["example.com", "example.net", "example.org"]`, reservados pela RFC 2606 e por isso nunca de pessoas reais. O usuário pode especificar outros se precisar; cada domínio é validado sintaticamente. Se algum não for reservado (nem `.test`/`.example`), a validação emite um **aviso**: os endereços podem existir de verdade;
    - `name_column` (opcional): coluna `nome_proprio` da **mesma linha** usada para montar a parte local (`joao.silva@example.com`). O gerador declara `depends_on = [name_column]` (DD-00 §3.5). Sem ela, ou quando o nome da linha é nulo, usa um nome sorteado das listas do locale;
    - `unique` (padrão `false`): com `true`, acrescenta à parte local o sufixo `.` + índice global da linha em base36. Como os índices são distintos, os endereços válidos da tabela também são. Os inválidos e nulos não entram na garantia;
    - `max_length` opcional, com padrão e teto 254 (RFC 5321).
  - **Parte local:**
    - o nome é normalizado (NFKD sem acentos, minúsculas, só `[a-z0-9]`);
    - o primeiro nome e o último sobrenome são unidos por um separador sorteado entre `.`, `_` e nenhum;
    - com probabilidade 0.3, recebe 2 dígitos no fim;
    - fica com no máximo 64 caracteres. Com `unique`, o nome é encurtado para caber o sufixo.
  - **Regra de validade** (`is_valid_email`):
    - a parte local casa com `^[a-z0-9]+([._][a-z0-9]+)*$` e tem ≤ 64 caracteres;
    - um único `@`;
    - cada rótulo do domínio casa com `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`, e o TLD é alfabético com ≥ 2 letras;
    - o total tem ≤ `max_length`.
  - **Inválidos** (`invalid_ratio`), com a variante sorteada entre: sem `@`, dois `@`, `..` na parte local, parte local começando com `.`, domínio sem TLD, espaço na parte local.
  - Funciona em qualquer locale que tenha listas de nomes.
- **Locale:**
  - o registry `locales` mapeia o locale para os recursos (listas de nomes e lorem) e contém `pt_BR`;
  - geradores com regra nacional (`cpf`, `rg`) declaram `supported_locales = {"pt_BR"}`, e usá-los em outro locale é erro de validação;
  - o locale efetivo segue a precedência coluna > tabela > schema;
  - novos mercados entram registrando um locale e geradores próprios via plugin.

**Trade-offs**
- **Snapshot de listas × Faker em runtime.** O snapshot garante determinismo entre versões. O custo é atualizar o snapshot manualmente.
- **`invalid_ratio` só para tipos com regra.** A semântica fica inequívoca: inválido = falha na verificação.
- **CPF sem base repetida.** Por DV, 111.111.111-11 é "válido", mas sistemas reais o rejeitam. Por isso esses valores ficam fora dos válidos.

### A.4 APIs

- `types.register(registry)` registra `string`, `char`, `int`, `float`, `decimal`, `boolean`, `date`, `time`, `timestamp`, `uuid`, `json`, `array`, `cpf`, `rg`, `cartao_credito`, `nome_proprio`, `email` e o locale `pt_BR`.
- Funções puras de validação reutilizáveis (usadas pelos testes e, no futuro, por pipelines):
  - `is_valid_cpf(str)`;
  - `is_valid_email(str)`;
  - `is_valid_rg_sp(str)`;
  - `luhn_is_valid(str)`;
  - `card_brand(str) -> str | None`.

### A.5 Guardrails e validações

1. Parâmetros desconhecidos ou fora de faixa geram `SchemaError` com caminho (`min > max`, `scale > precision`, `precision > 38`, `max_items > 1000`, `length > 255`, datas inválidas, decimais que não cabem em `precision`).
2. `max_length` obrigatório em `string`, com teto de 1.000.000. Não existe string sem limite.
3. `json`: profundidade ≤ 3, ≤ 50 campos e serialização com `ensure_ascii=False` e sem `NaN`/`Infinity`.
4. `invalid_ratio` só em `cpf`, `rg` e `cartao_credito`. Os inválidos são verificados por teste de propriedade.
5. Nenhuma importação de `random` ou `np.random` (teste de arquitetura do DD-00).
6. **E-mail:** domínios padrão reservados (RFC 2606). Domínio customizado não reservado gera aviso na validação. Os endereços nunca apontam para caixas reais por padrão.
7. **Dados sintéticos nunca coincidem de propósito com dados reais.** Mesmo assim, CPFs e cartões gerados são matematicamente válidos, então o README de `examples/tipos/` alerta para **não** usá-los fora de ambientes de teste.

### A.6 Testes unitários (obrigatórios, em `tests/types/unit/`)

| Alvo | Testes mínimos |
|---|---|
| cada primitivo | respeita limites (min/max, comprimentos 0..N, `precision`/`scale`); `LogicalType` correto para cada combinação de parâmetros; determinismo (mesmo `Draws`, mesmo resultado); índices não contíguos = lote contíguo; parâmetros inválidos geram erros com caminho |
| `string` | comprimento sempre ≤ N e ≥ `min_length`; cada `charset` só usa os caracteres permitidos; `lorem` nunca ultrapassa N |
| `decimal` | valores exatos (sem erro de float); cabem em `precision`; `min`/`max` como string |
| `timestamp`/`date`/`time` | limites inclusivos; `timezone` reflete no tipo Arrow; precisão em ms |
| `uuid` | versão 4 e variante RFC 4122 em 10^5 amostras |
| `json`/`array` | JSON parseável; campos na ordem declarada; `max_items` respeitado; profundidade > 3 é rejeitada |
| `cpf` | golden: `529.982.247-25` é válido; 10^5 válidos passam em `is_valid_cpf`; com `invalid_ratio=1`, 10^5 falham; nenhuma base repetida; `masked`/`unmasked` com o formato exato |
| `rg` | golden: base `12345678` gera DV `2`; o caso DV = `X` existe e passa na verificação `soma + 100·DV ≡ 0`; inválidos falham |
| `cartao_credito` | Luhn válido em 10^5; prefixo e comprimento conforme a bandeira; `brands`, `weights` e `extra_bins`; inválidos falham no Luhn; máscara Amex 4-6-5 |
| `email` | 10^5 válidos passam em `is_valid_email`; `invalid_ratio=1` ⇒ todos falham, com cada variante de inválido presente; domínio padrão ∈ reservados; `domains` customizado é usado e um domínio não reservado emite aviso; domínio sintaticamente inválido ⇒ `SchemaError`; `name_column` produz parte local derivada do nome da linha (`João da Silva` → `joao.silva`/`joao_silva`/`joaosilva`), nome nulo ⇒ nome sorteado; `name_column` inexistente ou de outro tipo ⇒ `SchemaError`; `unique=true` ⇒ 10^6 endereços válidos distintos; parte local ≤ 64 e total ≤ `max_length`; `max_length` > 254 ⇒ erro |
| `nome_proprio` | `gender` e `parts`; respeita `max_length`; independe da versão do Faker (usa o snapshot); `invalid_ratio` rejeitado |
| locales | precedência coluna > tabela > schema; `cpf` em locale ≠ `pt_BR` gera erro |
| propriedades (hypothesis) | para parâmetros aleatórios válidos, o gerador nunca lança erro e sempre respeita o `LogicalType` |

### A.7 Exemplos de features opcionais (em `examples/tipos/`)

| Arquivo | Demonstra |
|---|---|
| `todos-os-tipos.yaml` | uma coluna de cada primitivo com parâmetros não padrão |
| `nulos.yaml` | `null_ratio` em vários tipos |
| `documentos-invalidos.yaml` | `invalid_ratio` em `cpf`, `rg` e `cartao_credito`, para testar pipelines de validação |
| `email-enderecos.yaml` | `email` com `name_column`, `unique: true`, `domains` customizados e `invalid_ratio` |
| `formatacao.yaml` | `format: masked` × `unmasked` |
| `cartoes-bandeiras.yaml` | `brands`, `weights` e `extra_bins` |
| `locale-por-coluna.yaml` | locale no schema, na tabela e na coluna |
| `README.md` | o que cada exemplo mostra, o comando `dataipsum gen ...` e trechos da saída esperada |

### A.8 Critérios de aceitação

- **A-01** Os 17 tipos estão registrados no registry com os nomes exatos da tabela A.4.
- **A-02** Todos os geradores são vetorizados. A **meta de desempenho será definida pelo usuário depois**; até lá, o teste `slow` só mede e registra o tempo de 10^6 linhas por tipo, sem falhar.
- **A-03** 100% dos CPF, RG, cartões e e-mails gerados com `invalid_ratio = 0` passam nas funções de validação. Com `invalid_ratio = 1`, 100% falham.
- **A-04** Com `invalid_ratio = 0.2` em 10^5 linhas, a fração de inválidos está em 0.2 ± 0.01.
- **A-05** `format` produz exatamente os padrões `^\d{3}\.\d{3}\.\d{3}-\d{2}$` (CPF masked), `^\d{11}$`, `^\d{2}\.\d{3}\.\d{3}-[\dX]$` (RG masked) e `^\d{8}[\dX]$` (RG unmasked).
- **A-06** `string` com `max_length` N nunca produz mais de N caracteres. Comprimentos 0 e N ocorrem em 10^5 amostras com N ≤ 10.
- **A-07** Mesma seed ⇒ mesmos valores. Seed diferente ⇒ valores diferentes (probabilidade de colisão desprezível, testada).
- **A-08** `invalid_ratio` em `nome_proprio` ou em qualquer primitivo gera `SchemaError`.
- **A-09** Os testes de A.6 existem e passam. Os exemplos de A.7 existem, validam e têm README.

### A.9 BDD

```gherkin
# language: pt
Funcionalidade: Tipos primitivos e campos com regra

  Cenário: CPFs válidos por padrão
    Dado uma tabela "pessoas" com 10000 linhas e a coluna "cpf" do tipo "cpf"
    Quando eu gero os dados com seed 7
    Então todo valor de "cpf" passa na validação de dígito verificador mod 11
    E todo valor segue a máscara "000.000.000-00"

  Cenário: Proporção de CPFs inválidos
    Dado a coluna "cpf" com invalid_ratio 0.1 e format "unmasked"
    Quando eu gero 100000 linhas
    Então entre 9000 e 11000 valores falham na validação
    E todos os valores têm 11 dígitos

  Cenário: Cartões com Luhn e bandeira
    Dado a coluna "cartao" do tipo "cartao_credito" com brands ["visa", "amex"]
    Quando eu gero 1000 linhas
    Então todo número passa no algoritmo de Luhn
    E números que começam com 34 ou 37 têm 15 dígitos
    E números que começam com 4 têm 16 dígitos

  Cenário: RG no padrão SP
    Dado a coluna "rg" do tipo "rg"
    Quando eu gero 10000 linhas
    Então todo valor satisfaz soma ponderada + 100 × DV ≡ 0 mod 11
    E ao menos um valor termina em "X"

  Cenário: String respeita o tamanho máximo declarado
    Dado a coluna "bio" do tipo "string" com max_length 5
    Quando eu gero 10000 linhas
    Então nenhum valor tem mais de 5 caracteres
    E existem valores com 0 e com 5 caracteres

  Cenário: Endereço de e-mail derivado do nome e único
    Dado a tabela "clientes" com as colunas "nome" do tipo "nome_proprio" e "email" do tipo "email" com name_column "nome" e unique true
    Quando eu gero 100000 linhas
    Então todo "email" passa na validação de endereço
    E todo domínio é "example.com", "example.net" ou "example.org"
    E não há endereços repetidos
    E a parte local de cada endereço começa pelo primeiro nome normalizado da mesma linha

  Cenário: invalid_ratio proibido em nome próprio
    Dado a coluna "nome" do tipo "nome_proprio" com invalid_ratio 0.1
    Quando eu valido o schema
    Então recebo SchemaError informando que "nome_proprio" não suporta invalid_ratio
```

### A.10 Evolução da imagem

- **Fragmento:** nenhum (`docker/fragments/tipos.*` continuam vazios).
- **Mudança na imagem:** os dados embarcados (`types/data/bins.yaml`, `names_pt_BR.json` e a lista lorem) precisam estar declarados como *package data* no wheel. Sem isso, eles não entram no venv copiado para a imagem.
- **Testes** (`tests/docker/test_image_tipos.py`, marker `docker`): dentro do container, `dataipsum gen --table t --rows 100 --col c:cpf --col r:rg --col k:cartao_credito --col e:email --col n:nome_proprio -o /out --format csv` gera 100 linhas válidas, sem acesso à rede (`--network none`).
- **Critério A-10:** o smoke test acima passa com a imagem de `EXTRAS` vazio.

---

## Trilha B — Relações, chaves e determinismo (S2)

### B.1 Contexto e escopo

A trilha B implementa o `Planner` do DD-00 e o gerador `ref`:
- chaves primárias;
- chaves estrangeiras;
- relações 1:1, 1:N e N:N;
- cardinalidade, com a contagem de linhas filhas **derivada**;
- threads, só no mecanismo; o texto é da trilha C;
- ordem topológica;
- recálculo local de linhas (`pk_at`, `row_at`).

### B.2 Objetivos / Não-objetivos

- **Objetivo:** gerar qualquer FK **sem consultar dados já gerados**. Isso é essencial para a execução distribuída.
- **Objetivo:** contagens de filhos exatas por pai, conforme a cardinalidade (decisão do usuário).
- **Objetivo:** chunks de tamanho ≤ `chunk_size`, inclusive em tabelas derivadas. Única exceção: uma thread nunca é partida (B.3.6).
- **Não-objetivo:** auto-relacionamento, ciclos, PK composta fora de tabela ponte e FK para tabela com PK composta.

### B.3 Design

#### B.3.1 Chaves primárias (`primary_key.strategy`)

| Estratégia | Tipo da coluna | `pk_at(i)` | Garantia |
|---|---|---|---|
| `sequence` | `int` | `start + i·step` (padrão 1, 1) | única e ordenada. Validação: `start + step·(rows−1) < 2^63` |
| `seeded_int` | `int` | `start + feistel_perm(i)` sobre [0, rows) | única (bijeção) e embaralhada |
| `seeded_uuid` | `uuid` | ver abaixo | única por construção |
| `composite` | colunas `via` + `pair` | par (fk_via, fk_pair) | única pela amostragem sem reposição (B.3.5). Só em `many_to_many` |

- **`seeded_uuid`:**
  - os 64 bits altos são `mix(seed_table ^ i)`, com versão 4 nos bits de versão;
  - os 64 bits baixos são `(i XOR k) & (2^62−1)`, com `k = derive(seed_table, "uuid")`, e a variante RFC 4122 `10` fica nos 2 bits superiores;
  - como `i < 2^62` (garantido pelo limite de linhas), os 64 bits baixos são injetivos em `i`, e o UUID é **único sem colisões**.
- O valor de uma coluna de PK vem **sempre** da estratégia; o gerador do tipo não é chamado para ela. `null_ratio` da PK deve ser 0.

#### B.3.2 Permutação Feistel com cycle-walking (algoritmo novo, com pseudo-código)

Usada em `seeded_int`, na cobertura 1:1, na escolha de participantes de thread e na amostragem sem reposição do N:N. É vetorizada, com chaves por elemento.

```
perm(x, n, key):                       # bijeção de [0,n) em [0,n)
    h = ceil(bits(n) / 2);  mask = 2^h - 1
    repeat:
        L, R = x >> h, x & mask
        for r in 0..3:                  # 4 rodadas
            L, R = R, L ^ (mix(R ^ key ^ (r * 0x9E3779B97F4A7C15)) & mask)
        x = (L << h) | R
    until x < n                         # cycle-walking; domínio ≤ 4n ⇒ poucas iterações
    return x
```

A implementação usa arrays numpy uint64. O laço de cycle-walking age só sobre os elementos ainda ≥ n.

#### B.3.3 Referências (`type: ref`)

- `params.table`: tabela-alvo, com PK de coluna única. O valor é `pk_at(tabela_alvo, j)`, e o `LogicalType` é o da PK-alvo.
- **FK dirigente** (é a coluna `rows_from.via`): `j` = índice do pai que "gerou" a linha (B.3.4). `null_ratio` deve ser 0.
- **FK não dirigente:** `j` é sorteado no intervalo [0, P) do pai, sem consultar dados:
  - `distribution: uniform` (padrão);
  - `{zipf: {s}}`: s > 0. O rank r vem da CDF exata quando P ≤ 10^6, e da inversa contínua da Zipf truncada quando P > 10^6 (aproximação documentada).
  - Com `shuffle: true` (padrão), `j = perm(r−1, P, derive(seed_relation, "shuffle"))`. Assim a popularidade não fica correlacionada com a ordem da PK.
  - `null_ratio` é permitido.

#### B.3.4 Contagem derivada e cardinalidade (`rows_from`)

- **Tabela raiz:** tem `rows`.
- **Tabela filha:** tem `rows_from = {via, relation, cardinality | coverage, pair?}`. Pela decisão do usuário, o número de linhas **é derivado**.

**Cardinalidade** (`one_to_many`, `many_to_many`, `thread`). Por pai j, `card(j)` é sorteado com `Draws(seed_relation(filho, "card"))` usando `row = j`:

| Forma | Semântica |
|---|---|
| `{fixed: k}` | exatamente k, com k ≥ 0 |
| `{range: {min, max}}` | inteiro uniforme em [min, max], com 0 ≤ min ≤ max ≤ 10^6 |
| `{uniform: {mean, spread}}` | açúcar para `range` [mean − spread, mean + spread], com mean − spread ≥ 0. **Equivalente a `range`**; existe por legibilidade |
| `{zipf: {s, min=1, max}}` | Zipf truncada em [min, max] via CDF exata, com s > 0 e max ≤ 10^6. Gera cauda longa |

**`one_to_one`:**
- `coverage` ∈ (0, 1], padrão 1.0;
- linhas do filho = `round(coverage · P)`;
- o filho i aponta para o pai `perm(i, P, derive(seed_relation, "1:1"))`;
- a FK é **única** por ser bijeção, e o DDL marca UNIQUE (trilha F).

**Planejamento** (`Planner.plan`, streaming, O(P) vetorizado em blocos de 10^6 pais, memória O(nº de chunks)):
1. Ordem topológica (Kahn) do grafo cujas arestas são as colunas `ref` e os participantes de thread. Ciclo ou auto-referência geram `PlanError` com o caminho do ciclo.
2. Para cada tabela filha, percorre os pais em blocos, calcula `card(j)` e forma chunks de forma **gulosa**:
   - acumula pais enquanto o total de filhos ≤ `chunk_size`;
   - um único pai com mais filhos que `chunk_size` é **partido** em sub-chunks de `chunk_size` (exceto em `thread`, B.3.6).
3. Cada `ChunkSpec` guarda `first_row`, `rows` e `parent = {table, first_index, count, first_child_offset}`. O total da tabela é a soma de tudo.
4. Se a soma de todas as tabelas passar de `max_rows_total`, gera `ResourceLimitError` **antes** de gerar qualquer dado.

**Mapeamento filho → pai dentro de um chunk:** `np.repeat(indices_dos_pais, card(pais))`, fatiado a partir de `first_child_offset`. É O(tamanho do chunk) e não precisa de dados gerados.

**Trade-off:** a forma dos chunks depende de `chunk_size`, mas os **valores não**, porque as células são sorteadas pelo índice global (DD-00 §3.6).

#### B.3.5 N:N via tabela ponte

- `rows_from = {via: a_id, relation: many_to_many, pair: b_id, cardinality}` e `primary_key.strategy: composite`.
- Para o pai `a = j` com `k = card(j)` filhos, os `b` são `perm(0..k−1, |B|, derive(seed_relation, "pair:" + j))`. Isso dá **k valores distintos**, logo o par (a, b) é único sem consultar dados.
- **Validação no plano:** `max(card) ≤ |B|`, senão `PlanError`.

#### B.3.6 Threads (mecanismo; o texto é da trilha C)

- `rows_from = {via: thread_id, relation: thread, cardinality}`. A cardinalidade é o número de mensagens por thread, com máximo ≤ 1000.
- Bloco `thread`:
  - `participants: {table, count: <cardinalidade>, label_column}`, com count entre 2 e 10;
  - `start: {min, max}`, em timestamps ISO;
  - `gap_seconds: {min ≥ 1, max}`;
  - `llm: {...}`, lido pela trilha C.
- **Colunas implícitas determinísticas:**
  - `seq`: 1..N;
  - `autor`: ref para `participants.table`;
  - `timestamp`: estritamente crescente;
- **Colunas implícitas da trilha C:** `texto` (C preenche), `is_offensive` e `is_placeholder`.
- Esses nomes são **reservados** na tabela thread.
- **Como as colunas implícitas entram no schema:** `Planner.implied_columns(table)` (contrato do DD-00 §3.5) devolve as colunas da tabela thread, na ordem `seq`, `autor`, `timestamp`, `texto`, `is_offensive`, `is_placeholder`, e a normalização do schema as acrescenta. Os tipos são:
  - `seq`: `int32`, não nulo;
  - `autor`: tipo da PK de `participants.table`, não nulo;
  - `timestamp`: `timestamp(tz=false)`, não nulo;
  - `texto`: `string(thread.llm.max_length)` ou `text` (C.3.8);
  - as duas flags: `boolean`, não nulas.
- **Participantes** da thread j: `perm(0..c−1, |P|, derive(seed_relation, "part:" + j))`, portanto distintos.
- **Autor por mensagem:** o `seq 1` é o participante 0; os seguintes são sorteados entre os participantes **diferentes do autor anterior**.
- **Timestamp:** `start` uniforme em [min, max], e cada mensagem soma um `gap` uniforme em [min, max]. A sequência é estritamente crescente porque min ≥ 1.
- **Chunking:** uma thread **nunca** é partida entre chunks, porque a trilha C gera a thread inteira numa chamada. O chunk pode exceder `chunk_size` em até 1000 linhas.

#### B.3.7 Recálculo local (`pk_at`, `row_at`, `parent_index_of`)

- `pk_at(tabela, índices)`: O(1) por índice (B.3.1).
- `row_at(tabela, índices, colunas)`:
  - chama os geradores **determinísticos** com `RowBatch(rows=índices)` e o `Draws` da coluna. Se uma coluna pedida declara `depends_on` (ex.: `email` com `name_column`), as dependências são calculadas antes, na mesma ordem do construtor de chunk (D.3.2);
  - para uma FK dirigente de tabela derivada, localiza o chunk por busca binária em `first_row` e aplica o mapeamento B.3.4;
  - usa um cache LRU de 64 chunks por processo;
  - pedir uma coluna **não determinística** (`llm_*`) gera `PlanError`. A proibição em templates é validada pela trilha C.
- `GenContext.parent_rows` (DD-00) é implementado sobre `row_at`.

### B.4 APIs

- `relations.register(registry)` registra o gerador `ref` e o `Planner` padrão.
- `Planner.validate`, `plan`, `pk_at`, `parent_index_of` e `row_at`, conforme o DD-00 §3.5.
- Utilitários públicos:
  - `feistel.perm(x, n, key)`;
  - `cardinality.sample(spec, seed, parent_indices)`;
  - `graph.topological_order(schema)`.

### B.5 Guardrails e validações

1. Uma tabela tem exatamente um entre `rows` e `rows_from`. `via` precisa ser uma coluna `ref` da própria tabela, com `null_ratio = 0`.
2. `ref.table` precisa existir e ter PK de coluna única. FK para tabela com PK `composite` é erro.
3. Ciclos e auto-referência são erro, e a mensagem mostra o ciclo (`a → b → a`).
4. Cardinalidades:
   - faixas válidas;
   - `max ≤ 10^6` (thread ≤ 1000);
   - `mean − spread ≥ 0`;
   - `s > 0`;
   - `coverage ∈ (0,1]`.
   Campos incompatíveis com a relação (`coverage` em `one_to_many`, `cardinality` em `one_to_one`) geram erro.
5. Estratégia de PK compatível com o tipo da coluna. Overflow de `sequence` é validado. O limite de 2^62 linhas por tabela garante o `seeded_uuid`.
6. N:N: `max(card) ≤ |B|` é validado no plano.
7. `max_rows_total` é validado **antes** de qualquer escrita.
8. Nomes reservados em tabelas thread (`seq`, `autor`, `timestamp`, `texto`, `is_offensive`, `is_placeholder`).
9. O plano é serializável e reprodutível: o mesmo (schema, seed, chunk_size) produz um `RunPlan` idêntico, byte a byte, em JSON.

### B.6 Testes unitários (obrigatórios, em `tests/relations/unit/`)

| Alvo | Testes mínimos |
|---|---|
| `feistel.perm` | bijeção para n ∈ {1, 2, 3, 1000, 2^20+7}; determinismo; chaves diferentes ⇒ permutações diferentes; vetorização com chaves por elemento |
| estratégias de PK | `sequence` com start/step e overflow detectado; `seeded_int` único e dentro da faixa; `seeded_uuid` único em 10^6, com versão/variante corretas; `composite` só em N:N |
| `cardinality` | `fixed`, `range`, `uniform` (= `range` equivalente, mesmo resultado), `zipf` (média empírica vs. teórica); limites; parâmetros inválidos |
| `plan` | contagem derivada = Σ card; chunks ≤ `chunk_size`; pai com filhos > `chunk_size` partido; thread nunca partida; plano idêntico para a mesma entrada; `ResourceLimitError` antes da escrita |
| 1:1 | `rows = round(coverage·P)`; FK única; `coverage = 1` cobre todos os pais |
| N:N | pares únicos; `max(card) > |B|` gera `PlanError` |
| FK não dirigente | uniforme (qui-quadrado); zipf exata (P ≤ 10^6) e aproximada (P > 10^6); `shuffle`; `null_ratio` |
| grafo | ordem topológica; ciclo `a→b→a` e auto-referência com mensagem de caminho |
| threads | participantes distintos; autor ≠ anterior; timestamps estritamente crescentes; `seq` 1..N; nomes reservados |
| `row_at`/`pk_at` | igual à linha na posição correspondente do chunk gerado (com geradores fake); coluna LLM gera `PlanError`; o cache LRU não altera o resultado |
| validação | cada item de B.5 tem um teste de erro com o caminho correto |

### B.7 Exemplos de features opcionais (em `examples/relacoes/`)

| Arquivo | Demonstra |
|---|---|
| `um-para-muitos.yaml` | `range` e `zipf` para pedidos por usuário |
| `um-para-um.yaml` | `coverage: 0.7` (perfil opcional) |
| `muitos-para-muitos.yaml` | tabela ponte `pedido_produto` com PK `composite` |
| `cardinalidades.yaml` | `fixed`, `range`, `uniform` e `zipf` lado a lado |
| `chaves.yaml` | `sequence` (start/step), `seeded_int` e `seeded_uuid` |
| `fk-distribuicao.yaml` | FK não dirigente com `zipf` e `shuffle` |
| `thread-estrutura.yaml` | tabela thread (participantes, gaps) com `llm` apontando para FakeLLM/Ollama |
| `README.md` | explicação, comandos e saída esperada de cada um |

### B.8 Critérios de aceitação

- **B-01** Para cada FK gerada, existe no pai uma linha com a PK correspondente (integridade referencial verificada em 10^5 linhas, em todas as relações).
- **B-02** Em `one_to_many` com `range {1,3}`, todo pai tem entre 1 e 3 filhos, e o total da tabela filha é a soma exata.
- **B-03** Em `one_to_one` com `coverage 0.5` e P = 1000, o filho tem 500 linhas e FKs únicas.
- **B-04** Em N:N, não há par repetido.
- **B-05** Nenhuma chamada de geração de FK lê arquivos ou dados de outras tabelas. Teste com um sink que falha a qualquer leitura.
- **B-06** Os chunks têm ≤ `chunk_size` linhas, exceto os que contêm uma única thread longa.
- **B-07** `row_at(t, [i])` é igual à linha i obtida pela geração completa.
- **B-08** Mudar `chunk_size` não altera os valores gerados, só a divisão em arquivos.
- **B-09** Ciclos e auto-referências são rejeitados com o caminho do ciclo.
- **B-10** Os testes de B.6 existem e passam. Os exemplos de B.7 existem, validam e têm README.

### B.9 BDD

```gherkin
# language: pt
Funcionalidade: Relações e determinismo

  Cenário: Contagem de filhos derivada da cardinalidade
    Dado a tabela "usuarios" com 100 linhas
    E a tabela "pedidos" com rows_from via "usuario_id" one_to_many cardinalidade fixed 3
    Quando eu planejo a execução
    Então "pedidos" tem exatamente 300 linhas
    E cada usuário aparece exatamente 3 vezes em "pedidos.usuario_id"

  Cenário: FK sem consultar dados gerados
    Dado um schema com "usuarios" e "pedidos"
    E um sink que lança erro em qualquer leitura
    Quando eu gero apenas o chunk 5 de "pedidos"
    Então todas as FKs do chunk existem no intervalo de PKs de "usuarios"

  Cenário: Relação 1:1 com cobertura parcial
    Dado "usuarios" com 1000 linhas e "perfis" one_to_one com coverage 0.25
    Quando eu gero os dados
    Então "perfis" tem 250 linhas
    E "perfis.usuario_id" não tem valores repetidos

  Cenário: Tabela ponte sem pares repetidos
    Dado "pedidos", "produtos" com 50 linhas e "pedido_produto" many_to_many cardinalidade range 1..5
    Quando eu gero os dados
    Então nenhum par (pedido_id, produto_id) se repete

  Cenário: Ciclo entre tabelas
    Dado a tabela "a" com ref para "b" e a tabela "b" com ref para "a"
    Quando eu valido o schema
    Então recebo erro contendo "a → b → a"

  Cenário: Recalcular a linha do pai
    Dado seed 99 e a tabela "usuarios" com 10000 linhas
    Quando eu chamo row_at("usuarios", [4321], ["nome", "cpf"])
    Então o resultado é igual à linha 4321 da geração completa

  Cenário: Mensagens de thread em ordem temporal
    Dado a tabela thread "mensagens" com 4 a 12 mensagens por conversa e 2 participantes
    Quando eu gero os dados
    Então em cada thread_id os timestamps são estritamente crescentes por seq
    E duas mensagens seguidas nunca têm o mesmo autor
```

### B.10 Evolução da imagem

- **Fragmento:** nenhum.
- **Testes** (`tests/docker/test_image_relacoes.py`): dentro do container, `examples/relacoes/um-para-muitos.yaml` (montado em `/schemas`) gera as tabelas com integridade referencial, com `--network none`.
- **Critério B-11:** o smoke test passa com a imagem de `EXTRAS` vazio.

---

## Trilha C — Campos gerados por LLM (S3)

### C.1 Contexto e escopo

A trilha C implementa:
- os tipos `llm_post`, `llm_email`, `llm_contrato` e o conteúdo de threads (`llm_conversa`, usado no bloco `thread.llm`);
- os provedores (Ollama, OpenAI-compatível e Anthropic);
- templates de prompt com variáveis;
- toxicidade;
- os modos `unique` e `pool`;
- cache em disco;
- retry e backoff;
- o tratamento de falha (pendências e placeholders).

### C.2 Objetivos / Não-objetivos

- **Objetivo:** texto coerente com a linha e com o pai (`{autor.nome}`, `{produto}`), sem quebrar a execução distribuída.
- **Objetivo:** o job **nunca para** por falha de provedor. Os chunks ficam `pending_llm` e o `resume` completa depois.
- **Não-objetivo:** reprodutibilidade exata. É melhor esforço, com `temperature = 0` e `seed` quando o provedor suporta.
- **Não-objetivo:** escolher o modelo ideal. O modelo é configuração do usuário.
- **Não-objetivo:** recombinar frases entre textos do pool (decisão do usuário).

### C.3 Design

#### C.3.1 Provedores

- **Interface** `LLMProvider` (DD-00). Implementações:

  | `kind` | Transporte | JSON estruturado | seed |
  |---|---|---|---|
  | `ollama` (**padrão**) | `httpx` → `POST {base_url}/api/chat` | `format` com JSON Schema | `options.seed` |
  | `openai_compatible` (vLLM, LM Studio etc.) | `httpx` → `POST {base_url}/v1/chat/completions` | `response_format` `json_schema` quando suportado; senão, instrução no prompt | `seed` |
  | `anthropic` | SDK oficial (extra `[anthropic]`) | instrução no prompt + validação local | não suportado (melhor esforço) |

- **Configuração:** fica em `llm.providers` (DD-00 §3.3). Variáveis de ambiente definem ou sobrescrevem o provedor padrão:
  - `DATAIPSUM_LLM_PROVIDER` (kind);
  - `DATAIPSUM_LLM_BASE_URL`;
  - `DATAIPSUM_LLM_MODEL`;
  - `DATAIPSUM_LLM_API_KEY_ENV`;
  - `DATAIPSUM_LLM_MAX_CONCURRENCY`.
  - Precedência: CLI > env > schema.
- **Concorrência por provedor:** `max_concurrency` é aplicado com o `LLMLimiter` do executor (trilha D), que funciona entre processos e nós. Dentro de um chunk, as chamadas saem em um pool de threads limitado pelo mesmo semáforo.
- **Retry:**
  - erros `ProviderUnavailable`, `ProviderRateLimited`, timeout e `ProviderBadResponse` (vazio ou malformado) são retentados;
  - **backoff exponencial com full jitter**: `delay = U(0, min(max_delay_s, base_delay_s · 2^tentativa))`, com o jitter sorteado de `seed_chunk` (não vira dado);
  - `Retry-After` é respeitado quando presente;
  - `max_attempts` padrão é 5;
  - `ProviderRefusal` é retentado 1 vez e depois conta como falha do item.
- **Circuit breaker:**
  - depois de 3 chunks consecutivos com falha definitiva no mesmo provedor, ele é marcado **aberto** para o resto da execução;
  - os chunks LLM seguintes vão direto para o tratamento de falha (C.3.7), sem esperar retries;
  - o evento é registrado no log e no manifesto.

#### C.3.2 Colunas LLM e templates

- **Coluna:**
  - `type: llm_post | llm_email | llm_contrato`;
  - `max_length` opcional;
  - `params`:
    - `provider` (padrão `llm.default_provider`);
    - `prompt` (opcional; sobrescreve o padrão);
    - `system` (opcional);
    - `mode: unique | pool` (`unique`);
    - `pool_size` (50, entre 1 e 10.000);
    - `toxicity: block | allow | ratio` (`block`);
    - `toxicity_ratio` (só em `ratio`, 0 < x ≤ 0.5);
    - `on_failure: pending | placeholder` (`pending`);
    - `max_regenerations` (3).
- **`LogicalType`:** com `max_length` N, `string(N)`, e o texto é truncado na última fronteira de palavra ≤ N. Sem N, `text`. Esses tipos lógicos viram `VARCHAR(N)`/`TEXT` no DDL e `string` no Avro, **conforme o destino**.
- **Templates padrão** (pt-BR), em `llm/prompts/*.txt`, versionados. Cada tipo tem o seu:
  - post de rede social;
  - e-mail com assunto e corpo;
  - contrato com cláusulas numeradas;
  - conversa.
  - Se N existe, o template recebe a instrução "no máximo N caracteres".
- **Sintaxe de variáveis:**
  - `{coluna}`: coluna da mesma linha;
  - `{ref.coluna}`: coluna do pai, alcançado pela coluna `ref` chamada `ref` desta tabela. A coluna `ref` serve **só como caminho**;
  - `{{` e `}}` são chaves literais.
- **Chaves nunca viram texto** (decisão do usuário). O usuário refere-se a PK e FK **somente pelo nome da coluna**, para navegar até o pai; o **valor** de uma chave nunca é inserido em prompt ou texto. O controle do usuário sobre chaves se limita a declarar o tipo (`int` ou `uuid`) e a estratégia (B.3.1). Por isso:
  - `{ref}` sozinho ⇒ `SchemaError`;
  - `{col}` em que `col` é PK ou `ref` ⇒ `SchemaError`;
  - `{ref.col}` em que `col` é PK ou `ref` do pai ⇒ `SchemaError`;
  - o exemplo `{produto}` do RESEARCH se escreve `{produto_id.nome}`, com o nome da coluna FK seguido da coluna desejada do pai.
- **Parser próprio:**
  - reconhece só `{identificador}` ou `{identificador.identificador}`;
  - **não** usa `str.format`, `eval` nem Jinja, o que impede acesso a atributos e código arbitrário.
- **Validação do template** (`TemplateValidator`, chamado pelo loader):
  - variável inexistente ⇒ `SchemaError`;
  - `{ref.col}` em que `col` é `llm_*` no pai ⇒ `SchemaError` (RESEARCH: só colunas determinísticas do pai);
  - `{col}` apontando para outra coluna `llm_*` **da mesma linha** ⇒ `SchemaError`. É uma decisão de simplicidade: evita dependência entre chamadas LLM. Ver §6;
  - variável que resolve para o **valor** de PK ou FK ⇒ `SchemaError` (regra acima). A mesma regra vale para os marcadores dos textos do pool (C.3.4).
- **Renderização:**
  - os valores vêm de `ctx.same_row` e `ctx.parent_rows` (trilha B, `row_at`);
  - cada valor inserido é convertido para texto, com quebras de linha normalizadas e truncado em 500 caracteres;
  - o prompt renderizado é limitado a 16 KiB.

#### C.3.3 Modo `unique`

- Uma chamada por linha, com a seed `seed_llm(t, c, row)` (DD-00 §3.6) e `temperature` da configuração (padrão 0).
- Resultado passa pelo cache (C.3.6) e depois pela toxicidade (C.3.5).

#### C.3.4 Modo `pool`

- **Geração do pool:**
  - antes dos chunks da tabela, K = `pool_size` textos são gerados, com seeds `derive(seed_column, "pool:" + i)`;
  - o prompt do pool recebe o template **sem substituir as variáveis**: o modelo é instruído a manter os marcadores `{…}` literalmente;
  - os textos são armazenados no cache e em `<cache_dir>/pools/<tabela>.<coluna>.json`.
- **Validação de cada texto do pool:**
  - só podem aparecer marcadores que são variáveis válidas do template;
  - chaves que não formam um marcador válido são tratadas como texto literal;
  - um marcador desconhecido faz o texto ser regenerado, até `max_regenerations` vezes; se persistir, o texto é descartado.
- **Por linha:**
  - o índice é `draws.integers(slot 2, 0, K)`;
  - o texto escolhido é **preenchido** com os dados da linha pelo mesmo parser restrito;
  - depois é truncado em N.
- Sem recombinação de frases (decisão do usuário).
- Com `toxicity: ratio`, ver C.3.5.

#### C.3.5 Toxicidade

- **Classificador** (proposta concreta, **para revisão**), combinado:
  1. **Lista de palavras pt-BR** em `llm/toxicity/wordlists/pt_BR.txt`:
     - normalização: minúsculas, sem acentos, palavra inteira;
     - é sempre ativa e é o classificador "leve" mínimo;
  2. **Detoxify `multilingual`** (suporta pt), no extra `[toxicity]`, com o score `toxicity`.
  - O texto é ofensivo se **qualquer um** marcar: palavra da lista **ou** score ≥ `threshold`.
  - Configuração: `llm.toxicity = {classifier: auto | wordlist | detoxify, threshold: 0.5}`.
  - `auto` usa os dois se o extra estiver instalado. Se não estiver, usa só a lista e emite **um aviso**.
- **Modos por coluna:**
  - `allow`: nada é filtrado, e `is_offensive` reflete o classificador.
  - `block`:
    - conteúdo classificado ofensivo é **regenerado** com nova seed, derivada com sufixo `:regen:n`, até `max_regenerations`;
    - se esgotar (decisão do usuário):
      - o chunk **não é gravado**, e nenhum texto ofensivo ou falso vai para a saída;
      - o chunk fica `pending_llm`, com `toxicity_exhausted` incrementado nas flags;
      - o `resume` tenta de novo com seeds de regeneração novas (sufixo `:resume:<tentativa>`);
      - o comportamento vale mesmo com `on_failure: placeholder`, porque placeholder é só para falha de provedor.
  - `ratio` (**mantém X% ofensivo de propósito**, para testar moderação):
    - em `unique`, a linha com `draws.uniform(slot 3) < toxicity_ratio` recebe o **prompt ofensivo**; as demais recebem o normal;
      - linha-alvo "limpa" que sair ofensiva é regenerada, como em `block`;
      - linha-alvo "ofensiva" que sair limpa é aceita com `is_offensive = false`;
      - a proporção real é registrada nas flags;
    - em `pool`, round(K·ratio) itens do pool são gerados com o prompt ofensivo; a linha sorteia primeiro o subconjunto, com slot 3 < ratio, e depois o item.
- **Flags:**
  - toda linha de tabela com coluna LLM tem `is_offensive` (OR entre as colunas LLM da linha) e `is_placeholder`. `is_placeholder` só é `true` com `on_failure: placeholder` escolhido pelo usuário (C.3.7);
  - o preenchimento de placeholders do pool é reverificado pela lista de palavras.
- **Prompt ofensivo (guardrail):**
  - pede linguagem **rude, grosseira, palavrões e insultos genéricos** dirigidos a situações ou produtos;
  - **proíbe explicitamente**: discurso de ódio ou ataques a grupos protegidos (raça, etnia, religião, gênero, orientação sexual, deficiência, nacionalidade), ameaças, assédio sexual e qualquer conteúdo envolvendo menores;
  - o texto do prompt é fixo e **não** é sobrescrevível pelo schema.

#### C.3.6 Cache em disco

- **Chave:** `sha256` de JSON canônico com:
  - `kind`, host do `base_url`, `model`, `system`, prompt renderizado, `json_schema`, `temperature`, `max_tokens`, `seed`;
  - **nunca** a chave de API.
- **Layout:** `<cache_dir>/<aa>/<sha256>.json`, contendo `{text, created_at, model}`. A escrita é atômica (tmp + rename), e a leitura valida o JSON.
- `cache_max_mb` (padrão 2048): ao exceder, os arquivos mais antigos por `mtime` são removidos.
- `--no-cache` desliga o cache. Os modos `unique` e `pool` usam o cache (RESEARCH).

#### C.3.7 Falha do provedor, pendências e placeholder

1. Os retries (C.3.1) se esgotam em algum item do chunk ⇒ o chunk inteiro é tratado como falho para o LLM.
2. **`on_failure: pending`** (padrão):
   - o chunk **não é gravado**;
   - o resultado é `status: pending_llm`;
   - o resto do job continua. As tabelas filhas não dependem do texto LLM do pai, porque isso é validado.
3. **`on_failure: placeholder`** (RESEARCH §2.6: opcional; **só quando o usuário pede explicitamente** na coluna ou com `--llm-on-failure placeholder`):
   - o chunk é gravado com texto lorem determinístico (lista embarcada, sorteado por `Draws`, ≤ N);
   - `is_placeholder = true`;
   - `status: pending_llm`;
   - o `resume` regenera o chunk com o LLM e o **substitui atomicamente** (decisão do usuário).
4. **O motor nunca troca para placeholder por conta própria** (decisão do usuário). Com `pending`, um pai não gravado deixaria filhos órfãos em destinos que exigem integridade referencial (bancos). A solução é: **os filhos esperam o pai**.
   - Antes de gravar um chunk filho num sink com `capabilities.referential_integrity = true` (DD-00 §3.5), o worker calcula os índices de pai referenciados por **todas** as colunas `ref` do chunk. O cálculo é determinístico e não lê dados (trilha B).
   - Se algum índice cai num chunk pai que não está `done`, o chunk filho **não é gravado**. Ele volta `pending`, com `blocked_by: [{table, chunk_id}]` no manifesto.
   - O `resume` processa em ordem topológica: primeiro completa os pais `pending_llm` e depois os filhos bloqueados. A execução termina `partial` enquanto houver bloqueios.
   - Sinks de arquivo e Kafka não exigem integridade referencial, então os filhos são gravados normalmente.
5. `resume`:
   - reprocessa os chunks `pending_llm` e `failed`;
   - as colunas determinísticas saem idênticas;
   - graças ao cache, o texto de itens que já tinham sucesso também é reaproveitado.

#### C.3.8 Threads (conteúdo)

- **Configuração (`thread.llm`)** aceita os mesmos campos de uma coluna LLM (C.3.2), exceto `mode`/`pool_size`:
  - `provider`, `prompt`, `system`;
  - `max_length`: opcional; limita **cada mensagem** e define o tipo de `texto` (`string(N)` ou `text`);
  - `toxicity`, `toxicity_ratio`;
  - `on_failure`, `max_regenerations`.
- **Threads usam sempre `unique`** (decisão do usuário), com uma chamada por conversa. `mode` ou `pool_size` em `thread.llm` geram `SchemaError`.
- As regras de variáveis de C.3.2 valem aqui: `{thread_id.col}` navega até o pai da thread, e o valor de chaves nunca entra no prompt.
- **Preferencial: uma chamada por thread** com JSON estruturado:
  - o prompt informa assunto e contexto (variáveis do pai da thread `{thread_id.col}` e rótulos dos participantes via `participants.label_column`);
  - informa também **a ordem fixa dos autores por mensagem**, determinada pela trilha B;
  - informa N.
- **JSON Schema pedido:** `{"mensagens": [{"seq": int, "texto": str}]}` com exatamente N itens.
- **Validação da resposta:**
  - JSON parseável (≤ 1 MiB);
  - com mais de N itens, trunca em N;
  - com menos de N itens ou `texto` vazio, é falha de formato.
- **Fallback automático:**
  - após 1 falha de formato (com 1 nova tentativa), a thread passa a ser gerada **mensagem a mensagem**;
  - o prompt inclui o histórico das mensagens anteriores (as últimas 20, até 8 KiB);
  - o contador `thread_fallbacks` é incrementado.
- **Linhas:** cada mensagem vira uma linha. `thread_id`, `seq`, `autor` e `timestamp` vêm da trilha B; `texto` vem daqui.
- Toxicidade e `max_length` se aplicam por mensagem. Em `block`, só a mensagem ofensiva é regenerada, no modo mensagem a mensagem, com o histórico. Se esgotar, vale C.3.5: o chunk fica `pending_llm` e não é gravado.

### C.4 APIs

- `llm.register(registry)` registra:
  - os tipos `llm_post`, `llm_email`, `llm_contrato`;
  - o preenchedor de threads;
  - os provedores `ollama`, `openai_compatible` e `anthropic` (carregado só se o SDK estiver instalado);
  - os classificadores `wordlist` e `detoxify`.
- `LLMColumnFiller.fill(chunk_ctx, columns) -> (arrays, flags)`: chamado pelo construtor de chunks da trilha D depois das colunas determinísticas.
- `ThreadFiller.fill(chunk_ctx) -> (texto_array, flags)`.
- `PoolBuilder.build(table, column) -> Pool`: chamado pela trilha D antes dos chunks da tabela.

### C.5 Guardrails e validações

1. **Credenciais:**
   - só via `api_key_env`;
   - nunca aparecem em logs, manifesto, cache ou mensagens de erro;
   - um teste injeta `SEGREDO123` e procura esse valor em todos os artefatos.
2. **Transporte:**
   - provedores `anthropic` e `openai_compatible` com host **não local** exigem `https://`;
   - `http://` só é aceito para `localhost`, `127.0.0.1`, `::1` ou nomes de serviço sem ponto (ex.: `ollama` no compose);
   - com a flag `allow_insecure_http: true`, também é aceito, mas com aviso.
3. **Saída do LLM é dado não confiável:**
   - nunca é executada nem interpretada como template além do preenchimento restrito;
   - caracteres de controle são removidos (exceto `\n` e `\t`);
   - o tamanho da resposta é limitado (1 MiB);
   - o JSON é parseado com `json.loads` sob esse limite.
4. **Templates:** parser restrito, variáveis validadas e proibição de referências a colunas LLM; prompt ≤ 16 KiB.
5. **Conteúdo ofensivo:** `toxicity_ratio ≤ 0.5`; prompt ofensivo fixo, com proibições explícitas (C.3.5); a recusa do provedor é tratada como falha, sem contornos.
6. **Recursos:**
   - `max_concurrency` por provedor, entre 1 e 256;
   - `timeout_s` entre 1 e 600;
   - `max_tokens` derivado de N (≈ N/2 tokens + margem) ou 2048 sem N;
   - cache limitado por `cache_max_mb`.
7. **Circuit breaker** evita horas de retries contra um provedor fora do ar.
8. **Detoxify:**
   - baixa os pesos na primeira execução, da fonte oficial da biblioteca, para `DATAIPSUM_MODEL_CACHE`;
   - com `DATAIPSUM_OFFLINE=1`, não baixa, cai para a lista de palavras e emite um aviso.

### C.6 Testes unitários (obrigatórios, em `tests/llm/unit/`; nenhum faz chamada de rede real)

| Alvo | Testes mínimos |
|---|---|
| provedores | com `httpx.MockTransport`, cada `kind` monta o request correto (endpoint, modelo, seed, formato JSON) e mapeia 429/5xx/timeout/recusa para os erros tipados; `Retry-After` respeitado; chave de API nunca aparece em repr/log; exigência de `https` |
| retry/backoff | número de tentativas; jitter determinístico por `seed_chunk` (relógio falso); circuit breaker abre após 3 chunks e depois não chama o provedor |
| templates | parse de `{col}`, `{ref.col}`, `{{ }}`; erro em `{ref}` sozinho, em `{pk}`, em `{ref.pk_do_pai}` e em `{ref.outra_ref}` (valor de chave nunca vira texto); erro em variável inexistente, em coluna LLM do pai e em coluna LLM da mesma linha; `{a.b.c}` rejeitado; nenhum uso de `str.format` (teste de arquitetura); truncamento de valores e limite de 16 KiB |
| `unique` | seed por linha = `seed_llm`; truncamento em fronteira de palavra ≤ N; `LogicalType` `string(N)` × `text` |
| `pool` | K chamadas; marcadores desconhecidos causam regeneração/descarte; preenchimento correto; seleção por linha determinística; subconjunto ofensivo em `ratio` |
| toxicidade | lista de palavras (acentos, maiúsculas, palavra inteira); combinação OR; `auto` sem extra emite aviso; `block` regenera e, ao esgotar, deixa o chunk `pending_llm` sem gravar (inclusive com `on_failure: placeholder`); `resume` usa seeds novas; `ratio` com proporção-alvo em 10^4 linhas com FakeLLM/FakeToxicity; `allow` só marca; `is_offensive` como OR entre colunas |
| cache | chave estável e sem segredo; hit evita chamada; escrita atômica; eviction por tamanho; `--no-cache` |
| falhas | `pending` ⇒ chunk não gravado + `pending_llm`; `placeholder` ⇒ gravado + `is_placeholder` + `pending_llm`; o motor **nunca** troca para `placeholder` sozinho; com sink `referential_integrity`, chunk filho que referencia chunk pai não `done` fica `pending` com `blocked_by` e não é gravado |
| threads | `thread.llm.max_length` define o tipo de `texto` e limita cada mensagem; `mode`/`pool_size` em `thread.llm` ⇒ `SchemaError`; JSON válido com N; mais de N é truncado; menos de N/JSON inválido cai no fallback mensagem a mensagem com histórico; `thread_fallbacks` contado; toxicidade por mensagem |
| saída não confiável | caracteres de controle removidos; resposta > 1 MiB rejeitada; JSON malicioso (profundidade, tamanho) rejeitado |

### C.7 Exemplos de features opcionais (em `examples/llm/`)

| Arquivo | Demonstra |
|---|---|
| `ollama-local.yaml` | provedor padrão Ollama (usa o compose de dev do DD-02, trilha G) |
| `openai-compativel.yaml` | vLLM/LM Studio via `openai_compatible` |
| `anthropic.yaml` | provedor de nuvem com `api_key_env` (requer o extra `[anthropic]`) |
| `prompt-customizado.yaml` | override de `prompt`/`system` com `{autor.nome}` e `{produto_id.titulo}` (chaves só como caminho) |
| `pool.yaml` | `mode: pool` com `pool_size` |
| `toxicidade-ratio.yaml` | `toxicity: ratio` para testar moderação (requer `[toxicity]` para o classificador completo) |
| `toxicidade-block.yaml` | `toxicity: block` |
| `falha-placeholder.yaml` + `resume.sh` | `on_failure: placeholder` com provedor indisponível, seguido de `dataipsum resume` |
| `conversa.yaml` | thread com JSON estruturado e fallback |
| `README.md` | pré-requisitos (extra, provedor), comandos e saída esperada |

### C.8 Critérios de aceitação

- **C-01** Com FakeLLM, `llm_post`, `llm_email` e `llm_contrato` produzem texto não vazio. Com `max_length` N, nenhum valor passa de N.
- **C-02** `{usuario_id.nome}` no prompt é substituído pelo nome do usuário da FK. Comparação com `row_at`.
- **C-03** Referenciar uma coluna LLM do pai gera `SchemaError` na validação, antes de qualquer chamada.
- **C-04** Em `toxicity: block` com FakeToxicity, nenhuma linha final tem `is_offensive = true`.
- **C-05** Em `toxicity: ratio` com 0.1 em 10^4 linhas (FakeLLM que obedece o prompt ofensivo), a fração de `is_offensive` fica em 0.1 ± 0.02.
- **C-06** Em `mode: pool` com `pool_size` 10 e 1000 linhas, o provedor recebe exatamente 10 chamadas (mais as regenerações).
- **C-07** Uma segunda execução com cache faz 0 chamadas ao provedor.
- **C-08** Com o provedor indisponível e `on_failure: pending`, o job termina com `status: partial`, os chunks LLM ficam `pending_llm` e as tabelas sem LLM ficam `done`. Depois de o provedor voltar, `resume` deixa tudo `done`.
- **C-09** Com `placeholder`, os arquivos existem com `is_placeholder = true`. Após o `resume`, são substituídos e `is_placeholder = false`.
- **C-10** Thread com FakeLLM que devolve JSON inválido ⇒ fallback mensagem a mensagem, N linhas por thread e `thread_fallbacks > 0`.
- **C-11** Nenhum artefato (manifesto, log, cache) contém o valor da chave de API.
- **C-12** Os testes de C.6 existem e passam. Os exemplos de C.7 existem, validam e têm README.
- **C-13** Um template com `{usuario_id}`, `{id}` ou `{usuario_id.id}` gera `SchemaError`. Nenhum prompt enviado ao FakeLLM contém valores de PK ou FK (verificado em todos os prompts de uma execução completa).
- **C-14** Com `toxicity: block` e FakeToxicity que sempre marca ofensivo, o chunk fica `pending_llm`, nenhum arquivo dele é gravado e nenhuma linha com lorem aparece, mesmo com `on_failure: placeholder`.
- **C-15** Com sink fake `referential_integrity = true` e o provedor fora do ar em `pedidos` (pai de `itens`), os chunks de `itens` que referenciam chunks pendentes ficam `pending` com `blocked_by`. Depois do `resume`, tudo fica `done`, sem órfãos.
- **C-16** Em nenhum cenário o motor grava placeholder sem `on_failure: placeholder` explícito.

### C.9 BDD

```gherkin
# language: pt
Funcionalidade: Campos gerados por LLM

  Cenário: Texto coerente com o pai
    Dado "usuarios" com a coluna "nome" e "posts" com ref "autor" para "usuarios"
    E a coluna "conteudo" do tipo "llm_post" com prompt "Post de {autor.nome} sobre viagens"
    E um FakeLLM que ecoa o prompt recebido
    Quando eu gero os dados
    Então cada "conteudo" contém o nome do autor referenciado pela linha

  Cenário: Referência proibida a coluna LLM do pai
    Dado "usuarios.bio" do tipo "llm_post"
    E "posts.conteudo" com prompt "{autor.bio}"
    Quando eu valido o schema
    Então recebo SchemaError informando que só colunas determinísticas do pai podem ser referenciadas

  Cenário: Valor de chave nunca entra no prompt
    Dado a coluna "resenha" com prompt "Resenha do pedido {pedido_id}"
    Quando eu valido o schema
    Então recebo SchemaError informando que chaves só podem ser usadas como caminho, como "{pedido_id.coluna}"

  Cenário: Bloqueio esgotado não grava nada
    Dado a coluna "comentario" com toxicity "block" e max_regenerations 2
    E um FakeToxicity que marca todo texto como ofensivo
    Quando eu gero a tabela
    Então os chunks da tabela ficam "pending_llm"
    E nenhum arquivo da tabela é gravado

  Cenário: Filhos esperam o pai em destino com integridade referencial
    Dado um sink de banco e o provedor LLM indisponível para "pedidos"
    Quando eu gero "pedidos" e "itens"
    Então os chunks de "itens" que referenciam pedidos pendentes ficam "pending" com "blocked_by"
    Quando o provedor volta e eu executo "dataipsum resume"
    Então "pedidos" é concluído antes de "itens"
    E todos os chunks ficam "done"

  Cenário: Bloqueio de conteúdo ofensivo
    Dado a coluna "comentario" com toxicity "block"
    E um FakeLLM cuja primeira resposta contém "#ofensivo"
    Quando eu gero a linha
    Então o texto final não é ofensivo
    E "is_offensive" é false

  Cenário: Proporção intencional de conteúdo ofensivo
    Dado a coluna "comentario" com toxicity "ratio" e toxicity_ratio 0.1
    Quando eu gero 10000 linhas
    Então entre 8% e 12% das linhas têm "is_offensive" igual a true

  Cenário: Provedor fora do ar
    Dado o provedor "local" indisponível e on_failure "pending"
    Quando eu gero um schema com "usuarios" (sem LLM) e "posts" (com LLM)
    Então todos os chunks de "usuarios" estão "done"
    E todos os chunks de "posts" estão "pending_llm"
    E o status da execução é "partial"
    Quando o provedor volta e eu executo "dataipsum resume"
    Então todos os chunks estão "done"

  Cenário: Conversa com fallback
    Dado uma tabela thread com 6 mensagens por conversa
    E um FakeLLM que não devolve JSON válido
    Quando eu gero 10 conversas
    Então existem 60 linhas de mensagens
    E cada thread tem seq de 1 a 6
    E o manifesto registra thread_fallbacks igual a 10

  Cenário: Pool de textos
    Dado a coluna "resenha" com mode "pool" e pool_size 5
    Quando eu gero 1000 linhas
    Então o provedor recebeu no máximo 5 chamadas mais as regenerações
    E todas as linhas têm os marcadores preenchidos com dados da própria linha
```

### C.10 Evolução da imagem

- **`docker/fragments/llm.runtime.dockerfile`** (cache de modelos gravável, compatível com rootfs somente leitura):
  - `ENV DATAIPSUM_MODEL_CACHE=/var/cache/dataipsum/models`, com `TORCH_HOME` e `HF_HOME` apontando para o mesmo diretório. O Detoxify baixa o checkpoint via `torch.hub` e o tokenizer via Hugging Face;
  - cria o diretório com dono 10001.
- **`docker/fragments/llm.build.dockerfile`:**
  - `ARG PRELOAD_TOXICITY=0`;
  - com `PRELOAD_TOXICITY=1` e `toxicity` em `EXTRAS`, baixa os pesos do Detoxify multilingual **no build** para o diretório acima, e a imagem funciona offline;
  - o estágio final copia o diretório com `COPY --from=build`.
- **Configuração do provedor LLM:** só por env em runtime (`DATAIPSUM_LLM_PROVIDER`, `DATAIPSUM_LLM_BASE_URL`, `DATAIPSUM_LLM_MODEL`, `DATAIPSUM_LLM_API_KEY_ENV` + a variável da chave). A imagem **não** define valores padrão para essas variáveis, e a chave nunca é embutida.
- **Runtime com rootfs `read_only`:**
  - o diretório de modelos precisa ser um volume gravável. O compose de dev (DD-02, G.3.2) monta ali o volume nomeado `dataipsum-models`, e um volume nomeado vazio é inicializado com o conteúdo pré-baixado da imagem;
  - sem diretório gravável e sem pesos, o classificador cai para a lista de palavras com **aviso**, sem derrubar a execução (C.5 item 8). `DATAIPSUM_OFFLINE=1` impede qualquer download.
- **Testes** (`tests/docker/test_image_llm.py`):
  - as variáveis de cache apontam para o diretório com dono 10001;
  - `EXTRAS=toxicity` + `PRELOAD_TOXICITY=1` classifica offline (`--network none`) com rootfs `read_only`;
  - sem pesos e sem volume gravável, a execução segue com aviso;
  - `docker history` e `docker inspect` não contêm chaves de API.
- **Critério C-17:** os testes acima passam. A imagem de `EXTRAS` vazio continua sem `torch`.

---

## Trilha D — Execução, paralelismo e recursos (S4)

### D.1 Contexto e escopo

A trilha D implementa:
- o **orquestrador**: plano → tarefas → executor → sink → manifesto;
- o **construtor de chunks**, que executa dentro do worker;
- o executor **local** (multiprocessing, M1);
- o **monitor adaptativo** de recursos;
- o **limitador LLM** por provedor;
- `resume`;
- o executor **Ray** (M2).

### D.2 Objetivos / Não-objetivos

- **Objetivo:** streaming. Nenhuma tabela é materializada inteira; a memória é O(concorrência × chunk).
- **Objetivo:** respeitar tetos de CPU e RAM **considerando a carga de outros processos**.
- **Objetivo:** mesma seed ⇒ mesma saída não-LLM em local e em Ray, com qualquer número de workers.
- **Não-objetivo:** paralelizar o planejamento no M1, que é O(P) vetorizado no driver.
- **Não-objetivo:** autoscaling de cluster Ray. O cluster detecta nós, mas não os cria.
- **Não-objetivo:** transações exatamente-uma-vez no Kafka (trilha E).

### D.3 Design

#### D.3.1 Orquestrador (`generate`)

1. Carrega e valida o schema e verifica `<out>` (DD-00 §6). Monta o `RunPlan` (trilha B) e checa os limites.
2. Escreve o manifesto inicial com `status: running` e todos os chunks `pending`.
3. Se `emit_schema` foi pedido, chama `api.export_schema` para `<out>/_schema/` e registra em `emitted_schemas` (trilha F).
4. **Agendamento por grafo de dependências** (decisão do usuário: uma tabela só espera outra se estiverem relacionadas):
   - o grafo é o mesmo da ordem topológica (trilha B): uma aresta pai → filha para cada coluna `ref` e para os participantes de thread;
   - uma tabela fica **pronta** quando todas as tabelas das quais ela depende terminaram, ou seja, todos os chunks estão `done`, `pending_llm`, `failed` ou `pending` com `blocked_by`;
   - **tabelas sem relação entre si rodam em paralelo**, e as tabelas raiz começam todas juntas;
   - chunks de todas as tabelas prontas compartilham a mesma fila, limitada pela concorrência corrente;
   - ao ficar pronta, uma tabela com `mode: pool` constrói o pool primeiro (trilha C);
   - chunks filhos que referenciam chunks pai não `done` seguem C.3.7 item 4 quando o sink exige integridade referencial.
   - **Trade-off:** respeitar a dependência entre tabelas relacionadas mantém a ordem topológica do RESEARCH e as FKs válidas em bancos. Liberar as tabelas independentes evita a perda de paralelismo de uma barreira global.
5. O driver recebe `ChunkResult`s, atualiza o manifesto (flush em lote) e alimenta o monitor.
6. Encerra:
   - `completed` se todos os chunks estão `done`;
   - `partial` se há `pending_llm`, `pending` com `blocked_by` ou `failed` não fatal;
   - `failed` em erro fatal.
7. **Política de erro por chunk:**
   - exceção não fatal ⇒ o driver resubmete até 3 tentativas e depois marca `failed`;
   - **erros fatais** (`OutputDirError`, disco cheio `ENOSPC`, falha de autenticação do sink, `ManifestError`) param a execução imediatamente com `failed`.

#### D.3.2 Construtor de chunk (no worker)

A ordem de construção das colunas de um chunk é:
1. PK via `pk_at`;
2. refs (dirigente via mapeamento, não dirigentes via distribuição);
3. colunas implícitas determinísticas de thread;
4. demais geradores determinísticos, com a máscara de inválido do slot 1, **em ordem topológica das dependências dentro da linha**:
   - essas dependências são declaradas por `Generator.depends_on(column)` (DD-00 §3.5), como o `email` com `name_column`;
   - ciclo entre colunas é `SchemaError`;
5. máscara de nulos (slot 0);
6. colunas LLM, via `LLMColumnFiller`/`ThreadFiller`;
7. flags implícitas;
8. montagem do `RecordBatch` na ordem declarada, com as implícitas ao fim.

Em seguida o chunk vai para `sink.write_chunk`: **a escrita acontece no worker**, para não trafegar dados pelo driver. O sink é reconstruído no worker a partir de `SinkConfig` (picklable). O worker devolve o `ChunkResult` com o sha256 do conteúdo, quando o sink o fornece.

#### D.3.3 Executor local (M1)

- `ProcessPoolExecutor` com contexto **spawn**, que evita herdar locks e threads, e `max_workers = os.cpu_count()`.
- O driver mantém `em_voo ≤ concorrência_atual`, que é controlada pelo monitor.
- `LLMLimiter`:
  - um `multiprocessing.Manager().BoundedSemaphore(max_concurrency)` por provedor, passado no initializer dos workers;
  - cada `acquire` tem timeout de 600 s, para não travar para sempre.

#### D.3.4 Monitor adaptativo (psutil, AIMD)

- Amostra a cada 1 s:
  - `psutil.cpu_percent(interval=None)`, **do sistema inteiro**, o que inclui outros processos;
  - `psutil.virtual_memory().percent`.
- **Tetos:**
  - `cpu_max` padrão 70, faixa 10–100;
  - `mem_max` padrão 60, faixa 10–95;
  - configuráveis por CLI, env e `RunOptions`.
- **Concorrência inicial:** `max(1, floor(cpu_count · cpu_max / 100))`.
- **Regras:**
  - **acima do teto** (CPU > `cpu_max` ou RAM > `mem_max`) em 2 amostras seguidas ⇒ `c = max(1, c // 2)`, com cooldown de 5 s;
  - **folga** (CPU < `cpu_max` − 10 e RAM < `mem_max` − 10) em 3 amostras seguidas ⇒ `c = min(max_workers, c + 1)`;
  - **pressão crítica** (RAM > min(95, `mem_max` + 15)) ⇒ **pausa**: nenhuma submissão nova até a RAM voltar abaixo de `mem_max`;
  - **se RAM > 95% por 30 s com c = 1** ⇒ `ResourceLimitError` fatal, com a mensagem sugerindo reduzir `chunk_size`.
- As transições são logadas (nível INFO) e os contadores vão para o manifesto.
- A concorrência LLM é limitada **separadamente**, por provedor (`LLMLimiter`).

#### D.3.5 `resume`

1. Lê `<out>/_manifest.json`. Recusa se o schema passado tiver outro hash, ou se a versão major do dataipsum for diferente (DD-00).
2. Reutiliza o `RunPlan` e a seed gravados, **sem replanejar**.
3. Reexecuta os chunks `pending`, `failed` e `pending_llm`. Com `--llm-only`, só os `pending_llm`.
4. Antes, o sink limpa temporários órfãos (trilha E).
5. Os chunks são regravados de forma idempotente, com substituição atômica.

#### D.3.6 Executor Ray (M2; extra `[ray]`)

- **Conexão:** `executor: ray` e `ray_address` (`auto` ou `ray://host:10001`).
- **Detecção de nós:**
  - a cada 5 s, `ray.nodes()` informa os nós vivos; entradas e saídas são logadas e contadas no manifesto;
  - a concorrência máxima é a soma dos slots dos nós vivos;
  - novos nós são usados sem reiniciar o job.
- **Agendamento por recursos:**
  - cada `ChunkTask` vira `ray.remote(num_cpus=1, memory=estimativa)`, com a estimativa = `chunk_size` × largura estimada da linha;
  - chunks com colunas LLM pedem também `resources={"llm": 1}`: só nós iniciados com `--resources='{"llm": N}'` os executam (ex.: nós próximos a um servidor Ollama);
  - `num_gpus` para tarefas LLM é configurável (`ray.llm_task_gpus`, padrão 0);
  - o default é 0 porque o modelo roda no servidor LLM e a GPU é declarada no nó.
- **Tolerância a falhas:**
  - `max_retries=3` para falhas de sistema (nó que cai): o Ray **refaz** a tarefa em outro nó;
  - isso é seguro porque a geração é determinística e a escrita, idempotente.
- **Monitor distribuído:**
  - um ator leve `NodeMonitor` por nó (afinidade de nó) roda o mesmo AIMD da D.3.4 com psutil local e publica os slots permitidos;
  - o driver limita as tarefas em voo à soma desses slots;
  - **trade-off:** o Ray escolhe o nó e o driver controla só o total. É uma aproximação documentada.
- **Limitador LLM global:**
  - um ator nomeado `LLMSemaphore:<provedor>` com permissões com *lease* de 10 min;
  - uma permissão presa em nó que caiu é recuperada quando o lease expira.
- **Sistema de arquivos compartilhado:**
  - sinks de arquivo exigem que `<out>` seja visível por todos os nós no mesmo caminho;
  - no início, o driver grava um arquivo-sonda e uma tarefa por nó verifica se o enxerga;
  - se algum nó não enxergar, `ExecutorError` com uma mensagem clara.
- **Invariante:** para o mesmo schema e seed, os arquivos não-LLM gerados via Ray têm o mesmo sha256 que os da execução local.

### D.4 APIs

- `execution.orchestrator.generate(schema, options) -> RunResult` e `resume(out_dir, options) -> RunResult`, chamados pela façade.
- `LocalExecutor`, `RayExecutor`: implementam `Executor` (DD-00).
- `ResourceMonitor(cpu_max, mem_max, sampler)`: o `sampler` é injetável para testes.
- `build_chunk(task) -> ChunkResult`: função pura de worker.

### D.5 Guardrails e validações

1. Tetos de CPU/RAM validados nas faixas; monitor sempre ativo, sem opção de desligar; pausa e erro fatal sob pressão de memória.
2. Limite de linhas (`max_rows_total`) checado antes de qualquer escrita.
3. `spawn` em vez de `fork`; tarefas picklable e sem estado global.
4. Só o driver escreve o manifesto.
5. Timeouts: `acquire` do LLM em 600 s; lease no Ray; limite de tentativas por chunk.
6. **Segurança do Ray:**
   - o Ray **não tem autenticação**, então a documentação exige rede privada;
   - os exemplos nunca publicam as portas 8265/10001/6379 em interfaces públicas;
   - o driver emite um aviso se `ray_address` apontar para um IP público.
7. Erros fatais param o job, sem loop de retries em disco cheio ou credencial inválida.
8. Logs estruturados sem dados das linhas geradas: só contagens e IDs de chunk.

### D.6 Testes unitários (obrigatórios, em `tests/execution/unit/`)

| Alvo | Testes mínimos |
|---|---|
| orquestrador | agendamento por grafo: tabelas independentes rodam em paralelo; filha só começa depois que as tabelas das quais depende terminam; tabelas raiz começam juntas; `completed`/`partial`/`failed`; retry de chunk (3×) e `failed`; erro fatal interrompe; manifesto atualizado em lote; `emit_schema` chamado quando pedido (com fakes) |
| construtor de chunk | ordem de colunas; nulos aplicados depois do gerador; implícitas ao fim; PK nunca nula; determinismo do chunk reconstruído |
| executor local | resultados iguais com 1, 2 e 4 workers; respeita `em_voo ≤ c`; `spawn`; `LLMLimiter` nunca ultrapassa `max_concurrency` (contador compartilhado); timeout de `acquire` |
| monitor | com sampler falso: redução multiplicativa, aumento aditivo, cooldown, pausa por RAM crítica, erro fatal após 30 s; faixas de `cpu_max`/`mem_max` validadas |
| `resume` | reexecuta só os não `done`; `--llm-only`; recusa hash de schema diferente; não replaneja |
| Ray (marcados `ray`, com `ray.init(num_cpus=2)` local, sem rede externa) | mesma saída sha256 que a execução local; tarefa que mata o worker é refeita; `llm` custom resource direciona tarefas; `LLMSemaphore` com lease expirado recupera a permissão; a sonda de FS compartilhado falha quando simulada |

### D.7 Exemplos de features opcionais (em `examples/execucao/`)

| Arquivo | Demonstra |
|---|---|
| `tetos-de-recursos.sh` | `--cpu-max 50 --mem-max 40` e o log das transições do monitor |
| `resume.sh` | interromper (Ctrl+C) e retomar com `dataipsum resume` |
| `llm-concorrencia.yaml` | `max_concurrency` por provedor |
| `ray-local.sh` | cluster Ray local de 1 nó (`ray start --head`) + `--executor ray` (requer `[ray]`) |
| `ray-cluster/` | docker compose com head + 2 workers usando a **mesma imagem** (`EXTRAS=ray`), nó com `--resources='{"llm": 2}'`, rede interna sem portas públicas |
| `README.md` | explicação, comandos e saída esperada |

### D.8 Critérios de aceitação

- **D-01** A memória é O(concorrência × chunk): o RSS não cresce com o total de linhas, e 10^6 e 10^7 linhas dão picos equivalentes (tolerância de 20%). **Metas absolutas de memória e tempo serão definidas pelo usuário depois**; até lá, o teste `slow` só mede e registra.
- **D-02** Com um processo externo consumindo 90% de CPU (teste com stress sintético), a concorrência cai para 1 em até 5 s e volta a subir depois que o estresse termina.
- **D-03** Os arquivos de uma execução com 1 worker e com 4 workers têm sha256 idênticos.
- **D-04** Matar o processo no meio e executar `resume` produz arquivos idênticos aos de uma execução sem interrupção.
- **D-05** O número de chamadas LLM simultâneas nunca passa de `max_concurrency`, medido com FakeLLM instrumentado.
- **D-06 (M2)** Execução em Ray com 2 nós locais produz os mesmos sha256 da execução local. A queda de um worker durante a execução não perde nem duplica chunks.
- **D-07 (M2)** Tarefas com LLM só rodam em nós com o recurso `llm`.
- **D-08** Os testes de D.6 existem e passam. Os exemplos de D.7 existem e têm README.
- **D-09** Num schema com duas tabelas raiz independentes (`produtos`, `usuarios`) e uma filha (`pedidos` → `usuarios`), chunks de `produtos` e `usuarios` são executados ao mesmo tempo, e nenhum chunk de `pedidos` começa antes de `usuarios` terminar (verificado por timestamps de início/fim no FakeExecutor instrumentado).

### D.9 BDD

```gherkin
# language: pt
Funcionalidade: Execução e controle de recursos

  Cenário: Mesmo resultado com qualquer paralelismo
    Dado o schema "loja" com seed 42
    Quando eu gero com 1 worker em "out1" e com 4 workers em "out2"
    Então os arquivos de dados de "out1" e "out2" têm o mesmo sha256

  Cenário: Tabelas independentes em paralelo, relacionadas em ordem
    Dado as tabelas raiz "usuarios" e "produtos" e a filha "pedidos" com ref para "usuarios"
    Quando eu gero com 4 workers
    Então chunks de "usuarios" e "produtos" executam simultaneamente
    E o primeiro chunk de "pedidos" começa depois do último chunk de "usuarios" terminar

  Cenário: Respeitar o teto de CPU diante de outros processos
    Dado cpu_max 70
    E outro processo usando 95% da CPU
    Quando a geração está em andamento
    Então a concorrência é reduzida até 1
    E nenhuma nova tarefa é submetida acima da concorrência corrente

  Cenário: Pausa por pressão de memória
    Dado mem_max 60 e um sampler que reporta RAM 80%
    Quando o monitor avalia a carga
    Então nenhuma tarefa nova é submetida até a RAM ficar abaixo de 60%

  Cenário: Retomar após interrupção
    Dado uma execução interrompida com 3 de 10 chunks concluídos
    Quando eu executo "dataipsum resume" no diretório de saída
    Então apenas os 7 chunks restantes são gerados
    E o status final é "completed"

  Cenário: Nó Ray cai durante a execução (M2)
    Dado um cluster Ray local com 2 workers
    Quando um worker é encerrado durante a geração
    Então as tarefas dele são reexecutadas em outro nó
    E o resultado final é idêntico ao da execução local
```

### D.10 Evolução da imagem

- **`docker/fragments/execucao.runtime.dockerfile`:** `ENV RAY_USAGE_STATS_ENABLED=0`, que desliga a telemetria de uso do Ray e evita chamada de rede não solicitada.
- **Worker Ray com a mesma imagem** (M2), sem mudar o `ENTRYPOINT`:
  - a imagem é construída com `EXTRAS=ray`;
  - o worker roda com `docker run --entrypoint ray <imagem> start --address=<head>:6379 --block`;
  - o Ray grava em `/tmp/ray`, então com rootfs `read_only` o `/tmp` precisa ser `tmpfs`, como no exemplo `examples/execucao/ray-cluster/`.
- **Tetos de recursos:** `DATAIPSUM_CPU_MAX` e `DATAIPSUM_MEM_MAX` são lidos por env (DD-00 §3.8). A imagem não fixa valores.
- **Testes** (`tests/docker/test_image_execucao.py`):
  - `--entrypoint ray <img:ray> --version` funciona;
  - `RAY_USAGE_STATS_ENABLED=0`;
  - com `ray-cluster/` (head + 2 workers da mesma imagem, sem portas publicadas), `--executor ray` gera o mesmo sha256 da execução local (marcado `ray` + `docker`).
- **Critério D-10:** os testes acima passam. Head e workers usam a **mesma** tag de imagem.

---

## 3. Integração do motor (S5)

- **Depende de:** S1–S4. Usa `FakeSink`, `FakeLLM` e `FakeToxicity`; **não** depende do DD-02.
- **Conteúdo:**
  - troca os fakes internos pelas implementações reais de A, B, C e D;
  - testes ponta a ponta em `tests/integration/motor/`;
  - *golden hash* do schema de referência (usuários, produtos, pedidos, ponte, thread) com seed fixa.
- **Critérios:**
  - **I-01** Um schema com todas as relações, todos os tipos e colunas LLM (FakeLLM) roda em `LocalExecutor` e gera o número planejado de linhas por tabela.
  - **I-02** O sha256 dos batches bate com o golden versionado. Qualquer mudança exige atualização explícita do golden no PR, com justificativa.
  - **I-03** Integridade referencial: 100% das FKs resolvem.
  - **I-04** `resume` depois de uma falha simulada do FakeLLM termina em `completed`.
  - **I-05** O teste de arquitetura do DD-00 (sem `random`) passa com o código de todas as trilhas.
  - **I-06** (docker) A imagem montada com os fragmentos de A–D gera o schema de referência dentro do container (`--network none`, FakeLLM registrado por plugin de teste), com o mesmo golden hash de I-02. É a evolução da imagem prevista no DD-00 §3.12.4.

```gherkin
# language: pt
Funcionalidade: Motor integrado

  Cenário: Geração completa determinística
    Dado o schema de referência com seed 2026
    Quando eu gero com LocalExecutor, FakeSink e FakeLLM
    Então o hash dos dados é igual ao golden versionado
    E todas as FKs apontam para PKs existentes
```

## 4. Plano de implementação (steps para o `/task-creator`)

| Step | Trilha | Depende de | Paralelo com |
|---|---|---|---|
| S1 | A — Tipos e campos com regra | DD-00 | S2, S3, S4 e DD-02 (E–H) |
| S2 | B — Relações e determinismo | DD-00 | S1, S3, S4 e DD-02 |
| S3 | C — Campos LLM | DD-00 | S1, S2, S4 e DD-02 |
| S4 | D — Execução e recursos (local M1; Ray M2 como sub-entrega com critérios D-06/D-07) | DD-00 | S1, S2, S3 e DD-02 |
| S5 | Integração do motor | S1–S4 | trilhas do DD-02 |

Todo step entrega: código, os **testes unitários** da sua seção "Testes unitários", os **exemplos** da sua seção "Exemplos de features opcionais", a **evolução da imagem** da sua seção "Evolução da imagem" (fragmento + `tests/docker/test_image_<área>.py` + seção "Impacto na imagem" no PR; o build e o smoke test da imagem rodam em todo step) e os quality gates do DD-00 §3.2 passando.

## 5. Rastreabilidade (RESEARCH → este doc)

| RESEARCH | Onde |
|---|---|
| §1 primitivos, campos com regra, campos LLM, tabelas com relações | A, B, C |
| §1 execução local ou distribuída respeitando recursos | D |
| §2.4 primitivos (String, Char, Date, Timestamp, Int, Float, Boolean, UUID, Decimal, Time, JSON/Array) | A.3 |
| §2.4 `null_ratio` (padrão 0) | DD-00 §3.3/§3.6 + D.3.2 (aplicação) |
| §2.4 CPF mod 11, cartão Luhn + BIN, válidos por padrão | A.3 |
| §2.4 RG | A.3 (SP, decisão do usuário) |
| §2.4 `invalid_ratio`, máscara com/sem | A.3 |
| §2.4 locale pt_BR, por schema/coluna, pronto para outros mercados | A.3 |
| §2.4 extensibilidade (tipos externos via entry points) | DD-00 §3.4; exemplo em `examples/core/plugin/` |
| §2.5 PK determinística (sequência ou função da seed) | B.3.1 |
| §2.5 FK sem consultar dados gerados | B.3.3 |
| §2.5 relações 1:1, 1:N, N:N (tabela ponte) | B.3.4, B.3.5 |
| §2.5 cardinalidade fixa, faixa, uniforme, zipf | B.3.4 |
| §2.5 ordem topológica | B.3.4 (plano), D.3.1 (execução) |
| §2.5 linha do pai recalculada de (seed, tabela, índice) | B.3.7 |
| §2.6 provedor plugável: Ollama padrão, OpenAI-compatível, nuvem | C.3.1 |
| §2.6 template padrão + override; variáveis de outras colunas e FKs | C.3.2 |
| §2.6 só colunas determinísticas do pai | C.3.2 |
| §2.6 threads em JSON; linhas `thread_id`, `seq`, `autor`, `timestamp` crescente, `texto`; fallback | B.3.6, C.3.8 |
| §2.6 toxicidade `block`/`allow`/`ratio`, lista pt_BR + classificador leve, `is_offensive` | C.3.5 |
| §2.6 volume `unique`/`pool` + cache em disco | C.3.3, C.3.4, C.3.6 |
| §2.6 retry com backoff; pendentes no manifesto; job continua; `resume`; placeholder opcional | C.3.1, C.3.7, D.3.5 |
| §2.7 chunks em streaming | B.3.4, D.3.2 |
| §2.7 interface `Executor`: local (multiprocessing) e Ray | D.3.3, D.3.6 |
| §2.7 Ray: detecção de nós, recursos CPU/RAM/GPU/`llm`, refazer tarefas | D.3.6 |
| §2.7 teto configurável, monitor adaptativo psutil, LLM limitado por provedor | D.3.4, D.3.3 |
| §3 M1 (motor) e M2 (Ray) | S1–S5 |
| §4 escolher o classificador de toxicidade | C.3.5 (**proposta: lista + Detoxify multilingual, para revisão**) |
| §4 reprodutibilidade LLM é melhor esforço | C.2, C.3.3 |

## 6. Questões em aberto e riscos

- **Para revisão:** a tabela de BINs (A.3), sobretudo Elo e Hipercard, que têm faixas extensas.
- **Para revisão:** o algoritmo de RG-SP (A.3) deve ser confirmado contra uma fonte oficial da SSP-SP antes do merge do S1. O golden `12345678 → 2` segue a fórmula documentada.
- **Para revisão:** o classificador Detoxify multilingual (C.3.5) é "leve" em relação a LLMs, mas depende de `torch` (imagem maior).
- **Decisão de simplicidade a confirmar:** proibir que uma coluna LLM referencie outra coluna LLM da **mesma linha** (C.3.2).
- **Risco:** a aproximação contínua da Zipf em FKs não dirigentes com P > 10^6 (B.3.3) é documentada, mas não é exata.
- **Risco:** a espera entre tabelas relacionadas (D.3.1) ainda serializa cadeias longas pai → filho → neto. Uma otimização futura seria liberar essa espera para sinks sem integridade referencial, já que a geração não lê dados do pai.
