# Sink `kafka`

Demonstra o sink `kafka` (DD-02, trilha E, M3): producer idempotente
(`enable.idempotence=true`, `acks=all`), valor serializado em Avro via Schema
Registry e key = chave primária.

## Pré-requisitos

- Docker (para o Kafka + Schema Registry descartáveis deste exemplo);
- extra `kafka` instalado: `uv sync --extra kafka`.

## Comandos

```bash
cd examples/sinks/kafka
docker compose up -d
bash gerar.sh
uv run python consumidor.py
docker compose down -v
```

## Saída esperada

- Tópico `loja.usuarios` criado (via `create_topics=true`) com 20 mensagens;
- cada mensagem tem `key` igual ao `id` do usuário (string canônica; PK composta
  viraria texto JSON `[a, b]`, DD-02 E.3.3);
- `consumidor.py` desserializa cada valor via Avro/Schema Registry e confirma
  `key == str(valor["id"])` para todas as mensagens (cenário BDD "Kafka com chave
  igual à PK", DD-02 E.9).

## Opções relevantes

- `bootstrap_servers`, `schema_registry_url`;
- `topic_prefix` (aqui `loja.`, formando o tópico `loja.usuarios`);
- `create_topics=true` (só para ambientes de teste, nunca produção);
- `auto_register_schemas` (padrão `true`).

## Nota de integração

O valor Avro depende de `avro_schema(table)`, entregue pela trilha F
(`dataipsum.schema_io`, DD-02 §0). Até essa função existir no ambiente, `gerar.sh`
falha com uma mensagem clara indicando que `avro_schema` ainda não está
disponível — o encaixe acontece no step de integração S5.
