"""Sink `kafka` (DD-02, trilha E, M3, E.3.3): producer idempotente, valor Avro via
Schema Registry, key = PK. Exige o extra opcional `kafka` (`confluent-kafka
[avro,schemaregistry]`); só é registrado por `sinks.register` quando esse pacote
está instalável (E.4).

`chunk_state` é sempre `absent` (E.3.3): o Kafka não guarda estado consultável por
chunk, então quem decide o que já foi enviado é o manifesto.

Nota de integração (S5): `topic_prefix` deveria ter como padrão `<schema.name>.`
(E.3.3), mas o sink só recebe o `TableSpec` da própria tabela em `open()`, não o
`Schema` inteiro — não há como calcular esse padrão aqui. Por isso o padrão local é
`""`, e quem constrói `SinkConfig.options` (o worker, DD-01) deve passar
`topic_prefix` explicitamente a partir de `schema.name` quando quiser o
comportamento descrito em E.3.3.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, ClassVar, cast

import pyarrow as pa

from dataipsum.contracts.sink import ChunkState, RunContext, SinkCapabilities, SinkReceipt
from dataipsum.errors import SinkError
from dataipsum.schema.models import TableSpec
from dataipsum.sinks._db_control import validated_table
from dataipsum.sinks.schema_stubs import load_avro_schema_for, require_schema

DEFAULT_TOPIC_PREFIX = ""
DEFAULT_AUTO_REGISTER_SCHEMAS = True


def _producer_config(options: Mapping[str, object]) -> dict[str, object]:
    config: dict[str, object] = {
        "bootstrap.servers": str(options.get("bootstrap_servers", "")),
        "enable.idempotence": True,
        "acks": "all",
        "compression.type": "zstd",
        "linger.ms": 20,
    }
    security_protocol = options.get("security_protocol")
    if security_protocol is not None:
        config["security.protocol"] = str(security_protocol)
    sasl_mechanism = options.get("sasl_mechanism")
    if sasl_mechanism is not None:
        config["sasl.mechanism"] = str(sasl_mechanism)
    config.update(_env_credential(options, "sasl_username_env", "sasl.username"))
    config.update(_env_credential(options, "sasl_password_env", "sasl.password"))
    return config


def _schema_registry_config(options: Mapping[str, object]) -> dict[str, object]:
    config: dict[str, object] = {"url": str(options.get("schema_registry_url", ""))}
    config.update(
        _env_credential(options, "schema_registry_basic_auth_env", "basic.auth.user.info")
    )
    return config


def _env_credential(
    options: Mapping[str, object], option_key: str, config_key: str
) -> dict[str, object]:
    import os

    env_var_name = options.get(option_key)
    if env_var_name is None:
        return {}
    value = os.environ.get(str(env_var_name))
    if not value:
        raise SinkError(
            f"variável de ambiente '{env_var_name}' (opção '{option_key}') não definida ou vazia"
        )
    return {config_key: value}


def kafka_key(table: TableSpec, row: Mapping[str, object]) -> str:
    """Key = PK (E.3.3): string canônica se simples, texto JSON `[a, b]` se composta."""
    pk_columns = table.primary_key.columns
    if len(pk_columns) == 1:
        return str(row[pk_columns[0]])
    return json.dumps([row[name] for name in pk_columns], ensure_ascii=False)


class KafkaSink:
    capabilities: ClassVar[SinkCapabilities] = SinkCapabilities(
        atomic_chunk=True, replace_chunk=True, referential_integrity=False
    )

    def __init__(self, options: Mapping[str, object] | None = None) -> None:
        self.options: Mapping[str, object] = dict(options or {})
        self._table: TableSpec | None = None
        self._topic: str | None = None
        self._producer: Any = None
        self._key_serializer: Any = None
        self._value_serializer: Any = None

    def open(self, run: RunContext, table: object, arrow_schema: pa.Schema) -> None:
        self._table = validated_table(table)
        topic_prefix = str(self.options.get("topic_prefix", DEFAULT_TOPIC_PREFIX))
        self._topic = f"{topic_prefix}{self._table.name}"

        from confluent_kafka import Producer
        from confluent_kafka.schema_registry import (
            SchemaRegistryClient,
        )
        from confluent_kafka.schema_registry.avro import (
            AvroSerializer,
        )
        from confluent_kafka.serialization import (
            StringSerializer,
        )

        self._producer = Producer(_producer_config(self.options))
        self._key_serializer = StringSerializer("utf_8")

        if bool(self.options.get("create_topics", False)):
            _create_topic_if_missing(self.options, self._topic)

        avro_schema_for = load_avro_schema_for()
        schema_dict = avro_schema_for(require_schema(run), self._table.name)
        registry_client = SchemaRegistryClient(_schema_registry_config(self.options))
        auto_register = bool(
            self.options.get("auto_register_schemas", DEFAULT_AUTO_REGISTER_SCHEMAS)
        )
        self._value_serializer = AvroSerializer(
            registry_client,
            json.dumps(schema_dict),
            conf={"auto.register.schemas": auto_register},
        )

    def write_chunk(self, chunk_id: int, batch: pa.RecordBatch | object) -> SinkReceipt:
        from confluent_kafka.serialization import (
            MessageField,
            SerializationContext,
        )

        producer = self._require_producer()
        table = self._require_table()
        topic = self._require_topic()
        record_batch = cast(pa.RecordBatch, batch)
        delivery_errors: list[str] = []

        def _on_delivery(err: object, _msg: object) -> None:
            if err is not None:
                delivery_errors.append(str(err))

        context = SerializationContext(topic, MessageField.VALUE)
        for row in record_batch.to_pylist():
            producer.produce(
                topic,
                key=self._key_serializer(kafka_key(table, row)),
                value=self._value_serializer(row, context),
                on_delivery=_on_delivery,
            )
        producer.flush()
        if delivery_errors:
            raise SinkError(
                f"falha ao entregar {len(delivery_errors)} mensagem(ns) no tópico "
                f"'{topic}' (chunk {chunk_id}): {delivery_errors[0]}"
            )
        return SinkReceipt(sink_ref=f"kafka://{topic}/{chunk_id}")

    def chunk_state(self, chunk_id: int) -> ChunkState:
        return "absent"

    def close(self) -> None:
        if self._producer is not None:
            self._producer.flush()
            self._producer = None

    def _require_producer(self) -> Any:
        if self._producer is None:
            raise SinkError("sink não foi aberto: chame open() antes de write_chunk")
        return self._producer

    def _require_table(self) -> TableSpec:
        if self._table is None:
            raise SinkError("sink não foi aberto: chame open() antes de write_chunk")
        return self._table

    def _require_topic(self) -> str:
        if self._topic is None:
            raise SinkError("sink não foi aberto: chame open() antes de write_chunk")
        return self._topic


def _create_topic_if_missing(options: Mapping[str, object], topic: str) -> None:
    import confluent_kafka.admin as kafka_admin

    # `NewTopic` não está no __all__ do stub de `confluent_kafka.admin`, embora exista em
    # runtime; o cast evita depender de checagem de atributo contra o stub de terceiros.
    admin_module = cast(Any, kafka_admin)
    admin_client = admin_module.AdminClient(
        {"bootstrap.servers": str(options.get("bootstrap_servers", ""))}
    )
    partitions = int(cast(int, options.get("partitions", 1)))
    replication_factor = int(cast(int, options.get("replication_factor", 1)))
    futures = admin_client.create_topics(
        [
            admin_module.NewTopic(
                topic, num_partitions=partitions, replication_factor=replication_factor
            )
        ]
    )
    for future in futures.values():
        try:
            future.result()
        except Exception as exc:
            if "already exists" not in str(exc).lower():
                raise SinkError(f"falha ao criar o tópico '{topic}': {exc}") from exc
