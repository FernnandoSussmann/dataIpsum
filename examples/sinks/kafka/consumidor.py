"""Consumidor Avro de verificação (DD-02, trilha E, M3, E.6, E.7, E.9).

Confere o cenário BDD "Kafka com chave igual à PK": consome o tópico
`loja.usuarios` e imprime, para cada mensagem, a key (deve ser o `id` do
usuário) e o valor desserializado via Avro/Schema Registry. Exige o extra
`kafka`: `uv sync --extra kafka`.

Uso: `uv run python examples/sinks/kafka/consumidor.py`, depois de rodar
`gerar.sh` neste mesmo diretório.
"""

from __future__ import annotations

from confluent_kafka import Consumer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer
from confluent_kafka.serialization import MessageField, SerializationContext, StringDeserializer

TOPIC = "loja.usuarios"
BOOTSTRAP_SERVERS = "localhost:9092"
SCHEMA_REGISTRY_URL = "http://localhost:8081"
POLL_TIMEOUT_SECONDS = 5.0
MAX_MESSAGES = 20


def main() -> None:
    registry_client = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})
    value_deserializer = AvroDeserializer(registry_client)
    key_deserializer = StringDeserializer("utf_8")

    consumer = Consumer(
        {
            "bootstrap.servers": BOOTSTRAP_SERVERS,
            "group.id": "dataipsum-exemplo-verificacao",
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([TOPIC])

    seen = 0
    try:
        while seen < MAX_MESSAGES:
            message = consumer.poll(POLL_TIMEOUT_SECONDS)
            if message is None:
                break
            if message.error():
                raise RuntimeError(str(message.error()))
            key = key_deserializer(message.key())
            value = value_deserializer(
                message.value(), SerializationContext(TOPIC, MessageField.VALUE)
            )
            print(f"key={key!r} id_no_valor={value.get('id')!r} valor={value!r}")
            assert key == str(value.get("id")), "key deveria ser igual ao id (E-06/E.9)"
            seen += 1
    finally:
        consumer.close()

    print(f"{seen} mensagens verificadas: key == id em todas.")


if __name__ == "__main__":
    main()
