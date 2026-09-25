# Compose de desenvolvimento com Ollama

`docker-compose.yml` (raiz do repositório) sobe o dataIpsum junto com um
Ollama local, usando a mesma imagem única do DD-00 (§3.12): o `Dockerfile`
gerado na raiz, nunca uma imagem alternativa. É só para desenvolvimento —
publicar em registry e orquestrar clusters em produção ficam fora do escopo
(DD-02 §G.2).

## Subir o stack (CPU)

```bash
docker compose up -d ollama
docker compose up ollama-pull        # baixa o modelo e sai (one-shot)
docker compose run --rm dataipsum schema validate /schemas/loja.yaml
docker compose run --rm dataipsum gen /schemas/llm/ollama-local.yaml -o /out
```

`examples/llm/ollama-local.yaml` é entregue pela trilha C (LLM, DD-01); até
lá, qualquer schema em `examples/` montado em `/schemas` (somente leitura)
serve para testar `schema validate`/`gen`.

## Com GPU NVIDIA (profile `gpu`)

O serviço `ollama` roda em CPU por padrão. Para reservar uma GPU NVIDIA, use o
profile `gpu`, que ativa o serviço `ollama-gpu` no lugar de `ollama` (mesmo
alias de rede, então `dataipsum` continua falando com `http://ollama:11434`
sem mudar nada). **Não rode os dois ao mesmo tempo**: com `--profile gpu`,
peça explicitamente `ollama-gpu` em vez do `ollama` padrão.

```bash
docker compose --profile gpu up -d ollama-gpu
docker compose --profile gpu run --rm ollama-pull
docker compose --profile gpu run --rm dataipsum gen /schemas/llm/ollama-local.yaml -o /out
```

Requer o [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
instalado no host.

## O que o compose garante (DD-02 §G.3.2, §G.5)

- `ollama` **não publica porta** no host: só é alcançável na rede interna do
  compose, por `dataipsum` e `ollama-pull`.
- `ollama-pull` é um serviço one-shot: baixa `${DATAIPSUM_LLM_MODEL:-llama3.1:8b}`
  e sai; `dataipsum` só inicia depois dele terminar com sucesso.
- `dataipsum` roda como `user: "10001:10001"`, com `read_only: true` e
  `tmpfs: /tmp` — a única pasta gravável fora de `/out` e `/tmp` é o volume
  nomeado `dataipsum-models`, montado em `/var/cache/dataipsum/models` (pesos
  do modelo de toxicidade).
- `cap_drop: [ALL]` e `security_opt: [no-new-privileges:true]`.

## Verificando manualmente

```bash
docker compose config                     # valida o YAML e a interpolação
docker compose --profile gpu config       # idem, com o profile gpu ativo
docker compose up -d ollama
docker compose ps --format '{{.Name}}: {{.Health}}'   # aguarda "healthy"
```
