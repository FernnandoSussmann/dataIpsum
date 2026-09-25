# DD-00 — Status de implementação (para retomar depois)

Gerado automaticamente ao pausar o trabalho por limite de token. **Este arquivo
é um artefato de trabalho, não parte do design doc** — pode/deve ser apagado
quando o DD-00 for concluído e o PR aberto.

## Onde as coisas estão

- **Branch:** `feat/dd-00-fundacao-e-contratos` (checked out em
  `/home/mint/Documents/dataIpsum`), a partir de `main`.
- **Worktrees paralelas** (branches já mergeadas na branch acima, mas as
  worktrees em si ainda existem em disco — podem ser removidas com
  `git worktree remove <path>` quando não precisar mais delas):
  - `/home/mint/Documents/dataIpsum-worktrees/s2` — branch `feat/dd-00-s2-schema`
  - `/home/mint/Documents/dataIpsum-worktrees/s3` — branch `feat/dd-00-s3-seeds`
  - `/home/mint/Documents/dataIpsum-worktrees/s4` — branch `feat/dd-00-s4-manifesto`
  - `/home/mint/Documents/dataIpsum-worktrees/s5` — branch `feat/dd-00-s5-docker`
- Nenhum push feito ainda. Nenhum PR aberto ainda.
- Último commit em `feat/dd-00-fundacao-e-contratos`: `1277cfd` "DD-00:
  examples/core (§7.2) e teste de padrões de código (§7.1)".

## O que já foi feito (implementado, testado, mergeado nesta branch)

1. **S1 — Esqueleto, tooling e contratos**: `pyproject.toml` completo (deps,
   extras, dev deps, entry points, ruff/mypy/pytest/coverage/bandit config),
   `.pre-commit-config.yaml` (todos os hooks §3.2.1), `security/exceptions.yaml`
   + `scripts/check_security_exceptions.py`, árvore de pacotes de trilha com
   `register()` vazios, `contracts/*` (todos os Protocols), `errors.py`,
   `registry.py`, esqueleto de CLI (`dataipsum --help/--version`),
   `data_ipsum.py` removido.
2. **S2 — Modelo de schema**: `schema/models.py`, `loader.py` (YAML seguro,
   validação em 4 camadas, limites §6.1), `inline.py`, `jsonschema.py`,
   `config.py` (`RunOptions`, precedência CLI>env>schema>padrão).
3. **S3 — Seeds e Draws**: `seeds.py` completo (derive/mix/draw_u64/
   uniform/integers com rejeição de Lemire/choice/normal/`Draws`), golden
   values, teste de arquitetura anti-`random`.
4. **S4 — Manifesto, façade e fakes**: `manifest.py` (escrita atômica, flush
   em lote, confinamento de diretório, sanitizador de segredos),
   `api.py` (façade, delega para schema.loader; trilhas ainda não
   implementadas levantam `NotImplementedError("trilha X")`),
   `testing/fakes.py` (FakeSink/Executor/LLM/Toxicity/Planner/SchemaBuilder).
5. **S5 — Imagem Docker base**: `docker/Dockerfile.in`, 16 fragmentos vazios,
   `scripts/render_dockerfile.py`, `Dockerfile` gerado, `.dockerignore`,
   testes `tests/docker/test_image_base.py` (build real + smoke test passou:
   486.9 MiB sem extras, 583.9 MiB com um subconjunto de extras).
6. **Integração pós-merge**: `src/dataipsum/__init__.py` agora reexporta a
   façade `dataipsum.api`; conflito de merge em `tests/core/unit/conftest.py`
   resolvido (fixture `FULL_EXAMPLE` do S2 + stubs de costura do S4,
   convividos); `RunOptions` real exige `sink: SinkConfig` (um teste do S4
   usava o stub antigo com default, corrigido).
7. **Correções de gates encontradas rodando tudo mergeado**:
   - Bandit B506 (falso positivo em `_NoAliasSafeLoader`, subclasse de
     `yaml.SafeLoader`) — registrado como exceção em `security/exceptions.yaml`
     + `# nosec B506` inline, ambos parelhos.
   - `scripts/run_pip_audit.py` — corrigido para não tentar auditar o próprio
     pacote local (`--no-emit-project`) e para não usar `-r -` (stdin), que
     esta versão do pip-audit não aceita — usa arquivo temporário +
     `--disable-pip --no-deps` (evita precisar de um venv efêmero, que este
     sandbox não suporta por faltar `python3-venv`; o audit real contra
     OSV/PyPI continua rodando).
   - `examples/core/{seed-fixa,sem-seed,limites}.yaml` + `plugin/` (pacote
     mínimo com o gerador `exemplo_placa`, entry point, testado instalando e
     desinstalando de verdade) + `README.md` agregador — fecham a lacuna do
     §7.2 (antes só existia `examples/core/docker/`).
   - `tests/core/unit/test_code_standards.py` + fixtures em
     `tests/core/fixtures/code_standards/{violacoes,conformes}.py` — fecham a
     linha "padrões de código" da tabela §7.1 (roda `ruff --isolated` para
     ignorar o `per-file-ignores` do `pyproject.toml`, que existe só para as
     fixtures propositalmente ruins não quebrarem o gate principal).
   - `src/dataipsum/schema/loader.py`: variável genérica `data` renomeada
     para `parsed_document` (§3.10 proíbe nomes genéricos).

**Estado dos gates na branch agora** (verificado por último com HEAD em
`1277cfd`): `ruff check .` limpo, `ruff format --check .` limpo,
`mypy --strict src` limpo (0 erros — todos os módulos cross-step já existem
depois do merge), `pytest` (273 testes, 99.36% cobertura, gate ≥85% ok),
`bandit -r src -ll` limpo, `semgrep` limpo, `pip-audit` limpo,
`render_dockerfile.py --check` limpo, `pytest -m docker` passou (9 testes,
build real), `pre-commit run --all-files --hook-stage pre-commit` passou
inteiro (inclui gitleaks e hadolint via rede). `owasp-dependency-check`
falha explicitamente por falta de `NVD_API_KEY` — é o comportamento
esperado/documentado (§3.2.1, critério de aceitação 26), não um bug.

## Auditoria de spec (feita por um agente de revisão dedicado)

Um agente revisou a árvore mergeada contra o DD-00 inteiro, seção por seção.
Veredito geral: **implementação forte e fiel**; §3.6 (seeds) foi
reimplementado independentemente pelo revisor a partir do pseudocódigo cru do
doc e bateu byte-a-byte com os golden values do repo. As lacunas reais viraram
uma lista priorizada — **os itens 1 e 2 abaixo já foram corrigidos** (ver
seção anterior); o resto **ainda está pendente**:

### Pendente — Alta prioridade (falha um critério de aceitação nomeado)

1. ~~`examples/core/` incompleto~~ **FEITO** (commit `1277cfd`).
2. ~~`test_code_standards.py` + fixtures ausentes~~ **FEITO** (commit `1277cfd`).
3. **CI ausente** — não existe `.github/workflows/` nem nenhuma outra
   configuração de CI no repo. O doc exige (§3.12.3 item 1, critério de
   aceitação 30) um job `docker` obrigatório (build + smoke + `trivy image`
   falhando em `HIGH`/`CRITICAL` corrigível) em **todo** step de toda trilha,
   e (critério 25) que a CI rode `pre-commit run --all-files` mais os hooks
   de `pre-push`. **Nada disso está wireado ainda.** Isso é o maior buraco
   restante.
4. **`tests/core/unit/test_precommit_config.py` ausente** — a linha
   "pre-commit e segurança" da tabela §7.1 só está parcialmente coberta por
   `tests/core/unit/test_check_security_exceptions.py` (que testa só o
   validador de `security/exceptions.yaml`). Falta um teste que verifique:
   `.pre-commit-config.yaml` tem os hooks certos nos estágios certos, com
   `rev` fixo nos hooks de terceiros e `uv run` nos locais; que um
   `# nosec`/`# nosemgrep` sem entrada correspondente em
   `security/exceptions.yaml` é detectado (hoje **não há detector nenhum**
   disso — é puramente convenção); fixtures com vulnerabilidade conhecida
   (`subprocess(..., shell=True)` com entrada externa, `yaml.load` sem
   `SafeLoader`) reprovadas por bandit/semgrep.

### Pendente — Média prioridade (texto explícito do doc violado, sem AC numerado)

5. **`null_ratio == 0` em colunas de PK e na coluna `via` não é validado.**
   O doc (§3.3, tabela de colunas) diz explicitamente "Deve ser 0 em colunas
   de PK e na coluna `via`" — não há checagem nem teste disso em
   `schema/models.py`/`loader.py` hoje.
6. **`.dockerignore` contradiz o próprio comentário/doc sobre `.env*`.** O
   doc diz que `.env*` fica **fora da lista de exclusão do Dockerfile**
   deliberadamente ("para que segredos locais nunca entrem no contexto de
   build" — ou seja, o doc quer `.env*` **excluído/ignorado**, não incluído).
   O revisor confirmou que o arquivo atual tem um comentário que argumenta o
   oposto do texto do doc. **Ação:** reler §3.12.1 com calma (o texto do doc
   é um pouco denso nesse ponto) e garantir que `.env*` está de fato na lista
   do `.dockerignore`, com um comentário que reflita corretamente o motivo
   (nunca deixar segredo local entrar no contexto do build).
7. **Plumbing morto em `scripts/check_security_exceptions.py`.** As funções
   `bandit_skip_ids`, `semgrep_exclude_rule_ids`, `dependency_check_suppression_ids`
   (linhas ~82-91) existem mas **nunca são chamadas** pelos comandos reais do
   bandit/semgrep no `.pre-commit-config.yaml` nem por
   `scripts/run_dependency_check.py` — só `pip_audit_ignore_args` está de
   fato conectado (em `scripts/run_pip_audit.py`). Hoje isso é mascarado
   porque a única exceção existente (bandit B506) foi resolvida via
   `# nosec` nativo, não por essa plumbing. Se alguém registrar uma exceção
   de semgrep ou dependency-check no `security/exceptions.yaml` amanhã, ela
   vai **validar sem erro mas não suprimir nada de verdade** na ferramenta
   real. Precisa decidir: ou conecta de verdade (mudar os comandos do
   `.pre-commit-config.yaml`/`run_dependency_check.py` para consumir essas
   funções), ou documenta explicitamente que só bandit-via-nosec e
   pip-audit-via-flag são suportados hoje e as outras funções são
   scaffolding para quando surgir a primeira exceção real desse tipo.

### Pendente — Baixa prioridade (nitpicks, não bloqueantes)

8. `src/dataipsum/seeds.py:35` — `MAX_REJECTION_ATTEMPTS` é uma constante
   fixa do módulo; o doc diz que o teto de tentativas de rejeição é
   "declarado pelo gerador" (`Generator.draw_slots` existe mas não está
   conectado a esse teto). Não é exercitado ainda porque nenhum gerador real
   existe (escopo da trilha A/DD-01) — considerar só documentar a decisão de
   adiar no docstring, ou já conectar quando a trilha A chegar.
9. `tests/docker/test_image_base.py` builda um subconjunto de extras
   (`anthropic,postgres,mysql,kafka`) em vez do `EXTRAS=all` literal que o
   doc/§7.1 pedem (decisão consciente para não baixar `ray`/`torch` no teste
   — razoável, mas não é o texto literal do doc). Também não há teste
   confirmando que um `.env` perdido no contexto de build é de fato excluído
   (isso conecta com o item 6 acima).
10. `src/dataipsum/errors.py` (~linhas 57-69) — os quatro `# noqa: N818`
    (`ProviderUnavailable`, `ProviderRateLimited`, `ProviderRefusal`,
    `ProviderBadResponse`) compartilham um único comentário de justificativa
    acima do bloco, em vez de um por linha, como §3.10 pede literalmente
    ("`# noqa` pontual precisa de justificativa **na mesma linha**").
11. `src/dataipsum/contracts/types.py` (`to_arrow_type`) — `time` sempre
    mapeia para `time32("ms")`, nunca `"s"`; a notação do doc
    ("`time32[s|ms]`") é ambígua o suficiente para isso não ser um defeito
    claro, só uma nota.
12. `pyproject.toml`: o gate de cobertura (`fail_under = 85`) é medido
    globalmente sobre `src/dataipsum`, não "por pacote de trilha" como o
    texto literal do §3.2 pede. Inofensivo hoje (só o pacote core/DD-00 tem
    código real), mas quando as trilhas do DD-01/DD-02 chegarem em paralelo,
    uma trilha com cobertura baixa pode se esconder atrás de uma com
    cobertura alta num número global único. Vale reconsiderar a configuração
    de cobertura (ex.: `--cov` por pacote, ou um gate por diretório) quando
    isso passar a importar de verdade.

## Como retomar

1. `cd /home/mint/Documents/dataIpsum && git status` — deve estar limpo, em
   `feat/dd-00-fundacao-e-contratos`, HEAD em `1277cfd` (ou mais recente, se
   algo mais foi commitado depois deste arquivo ser escrito).
2. Reler a lista "Pendente" acima, de cima pra baixo (já está em ordem de
   prioridade).
3. Depois de resolver os itens pendentes, rodar a suíte completa de gates
   antes de abrir o PR:
   ```bash
   uv run ruff check . && uv run ruff format --check .
   uv run mypy --strict src
   uv run pytest -m "not integration and not slow and not ray and not docker" --cov --cov-report=term-missing
   uv run bandit -r src -c pyproject.toml -ll
   uv run semgrep scan --config p/owasp-top-ten --config p/python --error --metrics=off src
   uv run python scripts/run_pip_audit.py
   uv run python scripts/render_dockerfile.py --check
   uv run pytest -m docker -v   # builda imagem de verdade, ~40s
   uv run pre-commit run --all-files --hook-stage pre-commit
   ```
4. Depois de tudo verde, considerar remover as worktrees paralelas
   (`git worktree remove /home/mint/Documents/dataIpsum-worktrees/s{2,3,4,5}`)
   e as branches de step (`feat/dd-00-s2-schema` etc.) já mergeadas, se não
   forem mais precisas.
5. Apagar este arquivo (`design_docs/DD-00-implementation-status.md`) antes
   de abrir o PR — ele é um artefato de trabalho, não parte do design doc.
6. Abrir o PR contra `main`, com a seção "Impacto na imagem" (§3.12.3 item 4)
   preenchida — fragmentos ainda todos vazios nesta etapa, então a resposta
   é "nenhum" além da criação da imagem base em si.
