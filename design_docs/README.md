# Design Docs — dataIpsum

Estes documentos derivam de [`RESEARCH.md`](../RESEARCH.md), que registra as decisões de 2026-09-24, e das decisões confirmadas com o usuário listadas abaixo. Quando os dois divergem, **as decisões confirmadas prevalecem**. Os pontos marcados "para revisão" são propostas deste design.

## Índice

| Doc | Conteúdo | Onda |
|---|---|---|
| [DD-00 — Fundação e contratos](DD-00-fundacao-e-contratos.md) | tooling, pre-commit, formato do YAML, registry/plugins, interfaces, seeds/`Draws`, manifesto, façade, fakes, **imagem Docker base e sua evolução** | **0 (bloqueante)** |
| [DD-01 — Motor de geração](DD-01-motor-de-geracao.md) | trilhas paralelas **A** tipos · **B** relações · **C** LLM · **D** execução/recursos (+ Ray M2) | 1 |
| [DD-02 — Saídas, interfaces e entrega](DD-02-saidas-interfaces-e-entrega.md) | trilhas paralelas **E** sinks · **F** import/export · **G** CLI/compose · **H** contrato (M4) | 1 |

## Grafo de dependências e paralelização

```
                      ┌── A (S1) ─┐
                      ├── B (S2) ─┤
                      ├── C (S3) ─┼── DD-01 S5 (integração do motor) ──┐
DD-00 (S1→S2..S5)     ├── D (S4) ─┘                                    │
                      ├── E (S1) ─┐                                    ├── DD-02 S5 (ponta a ponta)
                      ├── F (S2) ─┤  (E-Kafka/create_tables usa        │
                      ├── G (S3) ─┤   ddl_for/avro_schema de F,         │
                      └── H (S4) ─┘   com stubs até o S5)  ─────────────┘
```

- **Onda 0:** DD-00. O S1 vem primeiro; depois S2, S3, S4 e S5 (imagem Docker base) rodam em paralelo.
- **Onda 1:** as **8 trilhas (A–H) rodam em paralelo**. Cada uma escreve só nos próprios diretórios e testa contra os fakes do DD-00.
- **Encadeados:** só os dois steps de integração (S5 do DD-01 e S5 do DD-02).
- **Para o `/task-creator`:** cada doc tem ≤ 5 steps (1 step = 1 trilha, + integração).

## Regras transversais (valem para todos os steps)

1. **Guardrails:** cada doc e cada trilha têm uma seção própria de guardrails e validações de segurança.
2. **Testes unitários obrigatórios:**
   - cada trilha lista seus testes mínimos na seção "Testes unitários";
   - os testes ficam em `tests/<área>/unit/`, sem rede, Docker ou LLM real;
   - cobertura ≥ 85% por pacote.
3. **Exemplos de features opcionais:**
   - quem implementa uma feature opcional (extras, opções de schema com padrão ou desligadas, opções de CLI) entrega um exemplo executável em `examples/<área>/`, com `README.md`;
   - a trilha H valida todos os exemplos em CI.
4. **Quality gates e pre-commit** (DD-00 §3.2 e §3.2.1). Um hook de pre-commit obrigatório roda:
   - `ruff`, `mypy --strict` e os testes unitários com cobertura;
   - **SAST**: bandit e semgrep com as regras OWASP Top 10;
   - **SCA**: pip-audit;
   - gitleaks e hadolint.
   No `pre-push` e na CI rodam também o **OWASP Dependency-Check** e os testes de integração; a imagem Docker passa pelo trivy na CI. Exceções só em `security/exceptions.yaml`, com expiração.
5. **Determinismo:** nenhuma fonte de aleatoriedade fora de `seeds.py`. Um teste de arquitetura garante isso.
6. **Padrões de código** (DD-00 §3.10):
   - escrita funcional e concisa, com `map`/`filter`/`reduce` ou compreensões no lugar de laços com acumulador;
   - vetorização numpy/pyarrow em dados em volume;
   - nomes que descrevem o comportamento;
   - comentários só quando o código não consegue expressar o porquê;
   - verificado pelo ruff e pela revisão de cada step.
7. **Imagem Docker evolutiva** (DD-00 §3.12):
   - a imagem é criada no DD-00 S5;
   - todo step reconstrói a imagem e roda o smoke test;
   - cada trilha evolui a imagem só pelo próprio fragmento `docker/fragments/<área>.*` e pelos próprios `tests/docker/test_image_<área>.py`;
   - o `Dockerfile` é gerado e não é editado à mão;
   - todo PR tem a seção "Impacto na imagem".
8. **Contratos congelados:** `contracts/`, `pyproject.toml` e `uv.lock` só mudam por PR de "mudança de contrato".

## Decisões confirmadas com o usuário (2026-09-24)

| Tema | Decisão |
|---|---|
| Escopo | M1–M3 completos; do M4, só o contrato (schema + esboço da API) |
| Idioma | pt-BR |
| Organização | 3 docs: DD-00 bloqueante + 2 docs agrupando trilhas paralelas |
| Questões abertas do §4 | Propostas concretas (formato do YAML em DD-00 §3.3; classificador em DD-01 C.3.5), para revisão |
| Linhas das tabelas filhas | Derivadas da cardinalidade por pai |
| Cardinalidade | `fixed` · `range {min,max}` · `uniform {mean, spread}` (açúcar para range) · `zipf {s, max}` |
| 1:1 | `coverage` (padrão 1.0) + FK única |
| RG | padrão SP mod 11 (DV 0–9 ou X) |
| `VARCHAR(n)` | N declarado pelo usuário (`max_length`); valores com 0..N caracteres. **Substitui** "maior valor gerado" |
| Texto LLM | `max_length` opcional → `VARCHAR(N)`; sem N → `TEXT` |
| `invalid_ratio` | só em tipos com regra (CPF, RG, cartão, e-mail) |
| E-mail | `email` = **endereço** válido (tipo com regra): domínios reservados por padrão, configuráveis; `name_column` da linha; `unique` opcional; `invalid_ratio` suportado. O **corpo** do e-mail é o template LLM `llm_email`. O import de DDL infere colunas `email` como endereço |
| Chaves em templates | PK/FK são referenciadas **só pelo nome da coluna**, como caminho (`{produto_id.nome}`); o valor de uma chave nunca vira texto. O usuário só define o tipo (`int`/`uuid`) e a estratégia |
| Padrões LLM | `toxicity: block`, `mode: unique`, `on_failure: pending`; formato de saída padrão `parquet`; `nome_proprio` com `max_length` padrão 120 |
| Agendamento | uma tabela só espera outra se estiverem relacionadas; tabelas independentes rodam em paralelo |
| Placeholder (lorem) | só se o usuário pedir `on_failure: placeholder`; o motor nunca troca sozinho. Com destino banco, os filhos **esperam** o pai pendente (`blocked_by`) |
| `block` esgotado | chunk fica `pending_llm`, nada é gravado; o `resume` tenta de novo |
| Threads | sempre `unique` (sem pool); `thread.llm.max_length` limita cada mensagem |
| `gen` em diretório com manifesto | erro, com sugestão de `resume` |
| Kafka | duplicatas em retry são aceitas (key = PK) |
| Códigos de saída | 0 sucesso, 1 qualquer erro (por enquanto) |
| Metas de desempenho e tamanho de imagem | a definir pelo usuário; os testes só medem |
| Pool LLM | K textos com placeholders preenchidos por linha; sem recombinação de frases |
| Placeholder por falha | chunk gravado, mas `pending_llm`; o `resume` regenera e substitui |

## Matriz de rastreabilidade (RESEARCH → docs)

| RESEARCH | Doc / seção |
|---|---|
| §1 Visão geral (primitivos, regras, LLM, relações, arquivos, local/distribuído) | DD-01 A, B, C, D · DD-02 E |
| §2.1 Python 3.12+, reescrita, biblioteca + CLI Typer, uv/src/pytest/ruff/mypy, extras | DD-00 §3.1, §3.2, §3.8 · DD-02 G |
| §2.2 YAML + Pydantic/JSON Schema, flags inline, contrato da UI | DD-00 §3.3 · DD-02 G.3.1, H |
| §2.3 import de DDL (sqlglot, PK/FK, inferência por nome) | DD-02 F.3.4 |
| §2.3 export DDL (PK/FK, `NOT NULL`, `VARCHAR(n)`, `DECIMAL(p,s)`) | DD-02 F.3.1 |
| §2.3 export Avro (logical types, union nula) | DD-02 F.3.2 |
| §2.3 `schema export`, `--emit-schema`, manifesto | DD-02 F.3.3 · DD-00 §3.7 |
| §2.3 Avro reutilizado no Kafka | DD-02 E.3.3 |
| §2.4 primitivos | DD-01 A.3 |
| §2.4 `null_ratio` | DD-00 §3.3, §3.6 · DD-01 D.3.2 |
| §2.4 CPF, RG, cartão, nome; válidos por padrão; `invalid_ratio`; máscara | DD-01 A.3 |
| §2.4 locale pt_BR, por schema/coluna, outros mercados | DD-01 A.3 |
| §2.4 registry único + entry points | DD-00 §3.4 |
| §2.5 seed opcional sorteada/registrada; tabela → coluna → chunk | DD-00 §3.6, §3.7 |
| §2.5 PK determinística; FK sem consultar dados | DD-01 B.3.1, B.3.3 |
| §2.5 1:1, 1:N, N:N; cardinalidade; ordem topológica; linha do pai recalculável | DD-01 B.3.4–B.3.7 · D.3.1 |
| §2.6 provedores (Ollama padrão, OpenAI-compatível, nuvem) | DD-01 C.3.1 |
| §2.6 templates + variáveis; só colunas determinísticas do pai | DD-01 C.3.2 |
| §2.6 threads JSON + linhas + fallback | DD-01 B.3.6, C.3.8 |
| §2.6 toxicidade `block`/`allow`/`ratio`, `is_offensive` | DD-01 C.3.5 |
| §2.6 `unique`/`pool` + cache em disco | DD-01 C.3.3, C.3.4, C.3.6 |
| §2.6 retry/backoff, pendentes, job continua, `resume`, placeholder | DD-01 C.3.1, C.3.7, D.3.5 |
| §2.7 chunks em streaming; `Executor` local/Ray | DD-01 D.3.2, D.3.3, D.3.6 |
| §2.7 Ray: nós, recursos CPU/RAM/GPU/`llm`, refazer tarefas | DD-01 D.3.6 |
| §2.7 teto configurável, monitor psutil adaptativo, LLM por provedor | DD-01 D.3.4, D.3.3 |
| §2.8 CSV/JSON/JSONL/Parquet; Postgres/MySQL/Kafka; escrita idempotente | DD-02 E.3 |
| §2.8 manifesto e retomada | DD-00 §3.7 · DD-01 D.3.5 |
| §2.9 Docker multi-stage, slim, não-root, `ENTRYPOINT`, `EXTRAS`, volumes, `.dockerignore` | DD-00 §3.12 (criada no S5) |
| §2.9 evolução da imagem (env LLM e cache de modelos, worker Ray, extras de sinks) | DD-00 §3.12.4 · DD-01 A.10–D.10 · DD-02 E.10–H.10 |
| §2.9 compose + Ollama | DD-02 G.3.2 |
| §2.10 UI fora do MVP; contrato; FastAPI; React + React Flow | DD-02 H |
| §3 M1 | DD-00; DD-01 A, B, C, D (local); DD-02 E (arquivos), F (export), G, H |
| §3 M1 remover `data_ipsum.py` e `study/` | DD-00 §3.1 (`study/` não existe no repo; ausência confirmada) |
| §3 M2 | DD-01 D.3.6 |
| §3 M3 | DD-02 E.3.2, E.3.3, F.3.4 |
| §3 M4 | DD-02 H (só contrato) |
| §4 classificador de toxicidade | DD-01 C.3.5 (proposta) |
| §4 formato exato do YAML | DD-00 §3.3 (proposta) |
| §4 reprodutibilidade LLM é melhor esforço | DD-01 C.2 |

## Pontos para revisão antes de implementar

- Formato do YAML (DD-00 §3.3): nomes `rows_from`, `via`, `pair`, `thread`; padrões `chunk_size = 10000` e `max_rows_total = 1e8`.
- Classificador de toxicidade: lista pt-BR + Detoxify multilingual (DD-01 C.3.5).
- Algoritmo do RG-SP, a confirmar contra fonte oficial, e tabela de BINs (DD-01 A.3).
- Proibição de coluna LLM referenciar outra coluna LLM da mesma linha (DD-01 C.3.2).
- Detalhes do gerador de e-mail: separadores, sufixo numérico e formato do sufixo `unique` (DD-01 A.3).
- Metas de desempenho e de tamanho de imagem, a definir (DD-01 A-02/D-01; DD-00 §7.1).
- Padrões do import de DDL e da inferência por nome (DD-02 F.3.4).
- Extras novos, fora da lista do RESEARCH: `[toxicity]`, `[anthropic]`, `[all]` (DD-00 §3.2).
