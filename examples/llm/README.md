# Exemplos da trilha C — campos gerados por LLM (DD-01)

Cada exemplo abaixo demonstra uma feature opcional da trilha C (§C.7). O motor
(`dataipsum.api.generate`, DD-01 §S5) já existe nesta branch, mas a CLI
`dataipsum gen`/`dataipsum resume` é da trilha G (DD-02) e não está nesta
branch; até o merge das duas, os exemplos documentam o schema e o comando
esperado, e podem ser inspecionados hoje com
`dataipsum.load_schema`/`dataipsum.validate` (ver o final deste arquivo).

## Pré-requisitos

- **Provedor local (Ollama)**: a maioria dos exemplos usa `kind: ollama` contra
  `http://localhost:11434`. Suba um Ollama local (`ollama serve` ou o compose de
  dev do DD-02, trilha G) e baixe o modelo (`ollama pull llama3.1:8b`) antes de
  rodar `dataipsum gen`.
- **`openai-compativel.yaml`**: precisa de um servidor compatível com a API da
  OpenAI (vLLM, LM Studio) em `http://localhost:8000`.
- **`anthropic.yaml`**: precisa do extra `[anthropic]` (`uv sync --extra anthropic`)
  e da variável de ambiente `ANTHROPIC_API_KEY`.
- **`toxicidade-ratio.yaml`**/**`toxicidade-block.yaml`**: funcionam com só a
  lista de palavras pt-BR (sempre ativa); o classificador completo (lista +
  Detoxify) precisa do extra `[toxicity]` (`uv sync --extra toxicity`).

## Exemplos

| Arquivo | Demonstra | Comando | Saída esperada |
|---|---|---|---|
| [`ollama-local.yaml`](ollama-local.yaml) | Provedor padrão Ollama, `mode: unique` | `dataipsum gen examples/llm/ollama-local.yaml -o <dir>` | `posts.conteudo` não vazio, ≤ 280 caracteres |
| [`openai-compativel.yaml`](openai-compativel.yaml) | vLLM/LM Studio via `openai_compatible` | `dataipsum gen examples/llm/openai-compativel.yaml -o <dir>` | `produtos.descricao` não vazio, ≤ 400 caracteres |
| [`anthropic.yaml`](anthropic.yaml) | Provedor de nuvem com `api_key_env` | `ANTHROPIC_API_KEY=... dataipsum gen examples/llm/anthropic.yaml -o <dir>` | `usuarios.bio` não vazio; nenhum artefato contém a chave |
| [`prompt-customizado.yaml`](prompt-customizado.yaml) | Override de `prompt`/`system` com `{autor_id.nome}` e `{produto_id.titulo}` | `dataipsum gen examples/llm/prompt-customizado.yaml -o <dir>` | cada `resenhas.texto` menciona o nome do autor e o título do produto referenciados pela linha |
| [`pool.yaml`](pool.yaml) | `mode: pool` com `pool_size: 50` sobre 1000 linhas | `dataipsum gen examples/llm/pool.yaml -o <dir>` | o provedor recebe no máximo 50 chamadas (mais regenerações); cada `resenha` tem o nome do usuário preenchido |
| [`toxicidade-ratio.yaml`](toxicidade-ratio.yaml) | `toxicity: ratio` (10%) para testar moderação | `dataipsum gen examples/llm/toxicidade-ratio.yaml -o <dir>` | entre 8% e 12% das linhas com `is_offensive = true` |
| [`toxicidade-block.yaml`](toxicidade-block.yaml) | `toxicity: block` | `dataipsum gen examples/llm/toxicidade-block.yaml -o <dir>` | nenhuma linha final com `is_offensive = true` |
| [`falha-placeholder.yaml`](falha-placeholder.yaml) + [`resume.sh`](resume.sh) | `on_failure: placeholder` com provedor indisponível, seguido de `dataipsum resume` | `dataipsum gen examples/llm/falha-placeholder.yaml -o /tmp/saida-placeholder` (provedor fora do ar), depois `bash examples/llm/resume.sh` | 1ª execução: arquivos gravados com `is_placeholder = true`, `status: pending_llm`; após o resume: `is_placeholder = false`, `status: done` |
| [`conversa.yaml`](conversa.yaml) | Thread com JSON estruturado e fallback mensagem a mensagem | `dataipsum gen examples/llm/conversa.yaml -o <dir>` | cada thread com `seq` de 1 até a cardinalidade sorteada; `thread_fallbacks` no manifesto conta as conversas que caíram no fallback |

## Validando os schemas hoje (sem a CLI `gen`)

```bash
uv run python -c "
from pathlib import Path
from dataipsum import load_schema, validate

for path in sorted(Path('examples/llm').glob('*.yaml')):
    schema = load_schema(path)
    report = validate(schema)
    print(path.name, '->', 'ok' if not report.errors else report.errors)
"
```

## Testes automatizados

`tests/llm/unit/` cobre o parser de templates, os provedores (com
`httpx.MockTransport`, nunca rede real), retry/backoff/circuit breaker, cache,
toxicidade, os modos `unique`/`pool` e threads — ver DD-01 §C.6 para a lista
completa. Rode com:

```bash
uv run pytest tests/llm -q
```
