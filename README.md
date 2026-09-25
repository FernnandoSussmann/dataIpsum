# dataIpsum

Gerador de dados sintéticos determinístico e extensível, com schema em YAML.

## Uso

```bash
uv sync --frozen
uv run dataipsum --help
```

Com extras (ex.: Ray, Postgres, MySQL, Kafka, toxicidade, Anthropic):

```bash
uv sync --frozen --extra ray --extra postgres
```

Todos os extras:

```bash
uv sync --frozen --all-extras
```

## Desenvolvimento

```bash
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run pytest -m "not integration and not slow"
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src
```

Os design docs em `design_docs/` descrevem a arquitetura (contratos, schema, motor de
geração, saídas e entrega). O legado (`data_ipsum.py`, Python 2) foi removido; a
biblioteca é reescrita do zero em Python 3.12+.
