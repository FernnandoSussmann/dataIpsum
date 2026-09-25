# Sink `postgres`

Demonstra o sink `postgres` (DD-02, trilha E, M3): `COPY` para carga em lote, tabela
de controle `_dataipsum_chunks` para escrita idempotente por chunk, e criação
opcional das tabelas via `create_tables=true`.

## Pré-requisitos

- Docker (para o Postgres descartável deste exemplo);
- extra `postgres` instalado: `uv sync --extra postgres`.

## Comandos

```bash
cd examples/sinks/postgres
docker compose up -d
bash gerar.sh
docker compose down -v
```

## Saída esperada

- A tabela `usuarios` no banco `dataipsum` com 100 linhas;
- a tabela de controle `_dataipsum_chunks` com uma linha `status = committed` por
  chunk gerado;
- rodar `bash gerar.sh` de novo **não duplica linhas**: cada chunk já `committed`
  na tabela de controle é pulado (E-04, DD-02 E.3.2).

## Opções relevantes

- `dsn_env=PG_DSN`: nome da variável de ambiente com a DSN (nunca a DSN em texto
  claro — só o **nome** da variável vai para o manifesto e os logs, DD-00 §6.5);
- `create_tables=true`: cria as tabelas do schema com `CREATE TABLE IF NOT EXISTS`
  antes de gravar (pensado para ambientes de teste, nunca produção);
- `db_schema` (padrão `public`) e `sslmode` (padrão `prefer`) também são aceitas.
