# Sink `mysql`

Demonstra o sink `mysql` (DD-02, trilha E, M3): `INSERT` em lotes de até 1000
linhas via `executemany`, `local_infile` sempre desligado, e a mesma tabela de
controle `_dataipsum_chunks` do sink `postgres` para escrita idempotente.

## Pré-requisitos

- Docker (para o MySQL descartável deste exemplo);
- extra `mysql` instalado: `uv sync --extra mysql`.

## Comandos

```bash
cd examples/sinks/mysql
docker compose up -d
bash gerar.sh
docker compose down -v
```

## Saída esperada

- A tabela `usuarios` com 100 linhas;
- `_dataipsum_chunks` com uma linha `status = committed` por chunk;
- rodar `bash gerar.sh` de novo não duplica linhas (E-04, DD-02 E.3.2).

## Opções relevantes

- `dsn_env=MYSQL_DSN`: nome da variável com a DSN (nunca a DSN em texto claro);
- `create_tables=true`: cria as tabelas com `CREATE TABLE IF NOT EXISTS`.
