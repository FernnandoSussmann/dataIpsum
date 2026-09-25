# Índice de exemplos (`examples/`)

Cada subpasta `examples/<área>/` demonstra as features opcionais de uma
trilha (DD-00 §3.2, "Regra transversal: exemplos de features opcionais").
`tests/contract/test_examples.py` (trilha H, DD-02 H.3.4) percorre **todo**
`examples/**/*.yaml` do repositório, valida cada um com `dataipsum.validate`
e com o JSON Schema publicado em
[`schemas/dataipsum-schema.v1.json`](../schemas/dataipsum-schema.v1.json), e
pula (com o motivo) os exemplos que exigem um extra não instalado
(`pip install dataipsum[<extra>]`).

## Subpastas existentes neste worktree

| Área | Trilha | Extra necessário | O que demonstra |
|---|---|---|---|
| [`core/`](core/README.md) | DD-00 (fundação) | nenhum | seed fixa/sorteada, limites (`chunk_size`, `max_rows_total`), plugin externo mínimo, uso básico da imagem Docker |
| [`contrato/`](contrato/README.md) | DD-02, trilha H | nenhum (o script de validação externa usa `check-jsonschema`, uma ferramenta à parte, não um extra do pacote) | o schema em JSON em vez de YAML, o menor schema válido, e a validação do contrato com uma ferramenta de JSON Schema externa |

## `examples/loja.yaml`

[`loja.yaml`](loja.yaml) (raiz de `examples/`, não uma subpasta) é o
**schema de referência** do projeto (DD-00 §3.3, DD-02 H.3.4): três tabelas
(`usuarios`, `produtos`, `pedidos`), uma relação `rows_from` (`pedidos`
depende de `usuarios`), uma coluna `llm_post` com a seção `llm`
correspondente, e colunas exercitando `null_ratio`, `invalid_ratio`,
`format` e `max_length`. É a referência que os exemplos e testes de outras
trilhas (`sinks/`, `schema-io/`, `cli-docker/`) passam a usar a partir da
integração do S5 (DD-02 §0, critério F-01) — essas subpastas ainda não
existem neste worktree porque suas trilhas (E, F, G) são implementadas em
paralelo, em worktrees próprios, e só chegam ao repositório na integração.

## Subpastas planejadas pelas outras trilhas do DD-02 (ainda não neste worktree)

A tabela abaixo antecipa o que a integração do S5 vai trazer, para quem
consulta este índice antes do merge (DD-02 §0):

| Área futura | Trilha | Extra necessário | O que vai demonstrar |
|---|---|---|---|
| `sinks/` | E — Sinks e escrita idempotente | `postgres`, `mysql` e `kafka` conforme o exemplo (`csv-opcoes.sh`, `jsonl-e-json.sh` e `parquet-compressao.sh` não exigem extra) | opções de CSV/JSONL/Parquet, e sinks de banco/Kafka com compose próprio |
| `schema-io/` | F — Import/export de schema | nenhum (`sqlglot` já está na base) | export de DDL (Postgres/MySQL) e Avro, `--emit-schema`, e import de DDL com o relatório "Revise:" |
| `cli-docker/` | G — CLI e compose de desenvolvimento | nenhum | flags inline, `--print-schema`, `--format`/`--sink-opt`, `--json`, e o compose de dev com Ollama |

Quando essas subpastas chegarem, esta seção é substituída pela entrada
definitiva na tabela de "Subpastas existentes" acima.
