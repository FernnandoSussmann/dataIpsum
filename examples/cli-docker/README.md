# Exemplos da área `cli-docker` (DD-02, trilha G)

Cada exemplo abaixo demonstra uma feature opcional da CLI (§G.7). `gen`,
`resume`, `schema export` e `schema import` dependem das trilhas D e F
(façade em stub, `NotImplementedError`) e por isso ainda **falham no fim**
quando chegam nesse ponto — o que os exemplos demonstram é o parsing, a
validação, os guardrails de segredo e a disciplina de stdout/stderr da CLI,
que já funcionam de ponta a ponta hoje.

| Arquivo | Demonstra | Comando | Saída esperada |
|---|---|---|---|
| [`inline.sh`](inline.sh) | Geração rápida com flags `--col` e `--print-schema` | `bash examples/cli-docker/inline.sh` | o YAML equivalente ao inline impresso no stdout; a geração de verdade falha com "trilha D" até o motor existir |
| [`formatos.sh`](formatos.sh) | `--format csv/jsonl/parquet` com `--sink-opt`, e o guardrail de segredos | `bash examples/cli-docker/formatos.sh` | `--sink-opt password=...` é recusado (código 1, sugestão `password_env`); `password_env=...` é aceito |
| [`json-saida.sh`](json-saida.sh) | `--json` para automação: stdout só com JSON, logs no stderr | `bash examples/cli-docker/json-saida.sh` | um único objeto JSON válido no stdout (`status: completed` ou `status: error`); progresso e erros no stderr |
| [`compose-ollama.md`](compose-ollama.md) | `docker compose up`, `docker compose run dataipsum gen ...` e o profile `gpu` | ver o arquivo | Ollama saudável, sem porta publicada; `dataipsum` roda como UID 10001, `read_only`, `cap_drop: [ALL]` |

## Rodando os exemplos

A partir da raiz do repositório, com `uv sync` já feito:

```bash
bash examples/cli-docker/inline.sh
bash examples/cli-docker/formatos.sh
bash examples/cli-docker/json-saida.sh
```

Todos os três usam `|| true` nos passos que dependem de `gen`/`resume` de
ponta a ponta (trilha D), para que o script inteiro rode e mostre a parte que
já funciona (parsing, validação, guardrails, formatação) mesmo com o motor
ainda em stub.

## Comandos sempre disponíveis

Estes já funcionam de ponta a ponta hoje, sem depender de nenhuma outra
trilha:

```bash
uv run dataipsum --version
uv run dataipsum --help
uv run dataipsum schema validate examples/core/seed-fixa.yaml
uv run dataipsum schema jsonschema
```
