"""Módulos fake de `confluent_kafka` (DD-02, E.6): permitem testar `KafkaSink` sem o
pacote `confluent-kafka` instalado nem um cluster real."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeProducer:
    config: dict[str, object]
    produced: list[dict[str, object]] = field(default_factory=list)
    flush_calls: int = 0
    fail_next_delivery: bool = False

    def produce(self, topic: str, key: object, value: object, on_delivery: Any) -> None:
        self.produced.append({"topic": topic, "key": key, "value": value})
        if self.fail_next_delivery:
            on_delivery(RuntimeError("erro simulado de entrega"), None)
        else:
            on_delivery(None, None)

    def flush(self) -> None:
        self.flush_calls += 1


class _IdentitySerializer:
    def __init__(self, *args: object, **kwargs: object) -> None:
        return None

    def __call__(self, value: object, ctx: object = None) -> object:
        return value


class FakeSchemaRegistryClient:
    def __init__(self, conf: dict[str, object]) -> None:
        self.conf = conf


class FakeAvroSerializer:
    def __init__(self, registry_client: object, schema_str: str, conf: object = None) -> None:
        self.registry_client = registry_client
        self.schema_str = schema_str
        self.conf = conf

    def __call__(self, value: object, ctx: object) -> object:
        return value


class FakeMessageField:
    VALUE = "value"


class FakeSerializationContext:
    def __init__(self, topic: str, field_: str) -> None:
        self.topic = topic
        self.field = field_


def install_fake_confluent_kafka(monkeypatch: Any) -> dict[str, object]:
    """Injeta os submódulos fake em `sys.modules`. Devolve um dict com as classes
    fake para as asserções do teste."""
    captured: dict[str, object] = {}

    root = types.ModuleType("confluent_kafka")

    def _make_producer(config: dict[str, object]) -> FakeProducer:
        producer = FakeProducer(config=config)
        captured["producer"] = producer
        return producer

    root.Producer = _make_producer  # type: ignore[attr-defined]

    admin = types.ModuleType("confluent_kafka.admin")
    admin.AdminClient = lambda conf: captured.setdefault("admin_client_conf", conf) or object()  # type: ignore[attr-defined]
    admin.NewTopic = lambda topic, num_partitions, replication_factor: {  # type: ignore[attr-defined]
        "topic": topic,
        "num_partitions": num_partitions,
        "replication_factor": replication_factor,
    }

    schema_registry = types.ModuleType("confluent_kafka.schema_registry")
    schema_registry.SchemaRegistryClient = FakeSchemaRegistryClient  # type: ignore[attr-defined]

    schema_registry_avro = types.ModuleType("confluent_kafka.schema_registry.avro")
    schema_registry_avro.AvroSerializer = FakeAvroSerializer  # type: ignore[attr-defined]

    serialization = types.ModuleType("confluent_kafka.serialization")
    serialization.StringSerializer = _IdentitySerializer  # type: ignore[attr-defined]
    serialization.SerializationContext = FakeSerializationContext  # type: ignore[attr-defined]
    serialization.MessageField = FakeMessageField  # type: ignore[attr-defined]

    for name, module in (
        ("confluent_kafka", root),
        ("confluent_kafka.admin", admin),
        ("confluent_kafka.schema_registry", schema_registry),
        ("confluent_kafka.schema_registry.avro", schema_registry_avro),
        ("confluent_kafka.serialization", serialization),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    return captured
