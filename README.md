# dataIpsum

Gerador de dados sintéticos determinístico e extensível, com schema em YAML.

## Status

A fundação (DD-00) está implementada: contratos (`src/dataipsum/contracts/`), carregamento e
validação do schema YAML (`src/dataipsum/schema/`) e os fakes usados pelos testes
(`src/dataipsum/testing/`). O motor de geração e as saídas (DD-01/DD-02 — trilhas de tipos,
relações, LLM, execução, sinks e schema-io) ainda não foram implementados: esses pacotes são
esqueletos e o comando `dataipsum generate` levanta `NotImplementedError`. Veja
[`design_docs/`](design_docs/README.md) para o roteiro e o estado de cada trilha.

## Uso

```bash
uv sync --frozen
uv run dataipsum --help
uv run dataipsum --version
```

Com extras (ex.: Ray, Postgres, MySQL, Kafka, toxicidade, Anthropic):

```bash
uv sync --frozen --extra ray --extra postgres
```

Todos os extras:

```bash
uv sync --frozen --all-extras
```

## Docker

O `Dockerfile` da raiz é **gerado**, não editado à mão: ele nasce de `docker/Dockerfile.in`
mais os fragmentos por trilha em `docker/fragments/<área>.{build,runtime}.dockerfile`.

```bash
uv run python scripts/render_dockerfile.py          # regenera o Dockerfile após mudar um fragmento
docker build --build-arg EXTRAS=postgres,ray -t dataipsum .
```

## Desenvolvimento

```bash
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run pytest -m "not integration and not slow and not ray and not docker" --cov --cov-fail-under=85
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src
```

O hook de pre-commit também roda bandit, semgrep, pip-audit, gitleaks e hadolint; o pre-push
adiciona OWASP Dependency-Check e os testes de integração (DD-00 §3.2.1).

## Design docs

`design_docs/` descreve a arquitetura em três documentos: [DD-00](design_docs/DD-00-fundacao-e-contratos.md)
(fundação bloqueante — tooling, schema, registry, seeds, imagem Docker),
[DD-01](design_docs/DD-01-motor-de-geracao.md) (motor de geração: tipos, relações, LLM,
execução/recursos) e [DD-02](design_docs/DD-02-saidas-interfaces-e-entrega.md) (saídas, sinks,
import/export, CLI/compose, contrato da UI). O legado (`data_ipsum.py`, Python 2) foi removido;
a biblioteca é reescrita do zero em Python 3.12+.
