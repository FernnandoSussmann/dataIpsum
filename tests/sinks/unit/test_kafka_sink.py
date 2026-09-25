"""Testes do sink `kafka` (DD-02, E.3.3, E.6): producer/serializer fake, sem cluster
real nem `confluent-kafka` instalado."""

from __future__ import annotations

import pyarrow as pa
import pytest
from tests.sinks._kafka_fakes import FakeProducer, install_fake_confluent_kafka
from tests.sinks.conftest import make_column, make_run_context, make_table

import dataipsum.schema_io as schema_io_module
from dataipsum.errors import SinkError
from dataipsum.sinks.kafka_sink import KafkaSink, kafka_key


@pytest.fixture
def fake_kafka(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured = install_fake_confluent_kafka(monkeypatch)
    monkeypatch.setattr(
        schema_io_module,
        "avro_schema",
        lambda table: {"type": "record", "name": table.name},
        raising=False,
    )
    return captured


def test_capabilities_no_referential_integrity() -> None:
    assert KafkaSink.capabilities.referential_integrity is False


def test_kafka_key_simple_pk() -> None:
    table = make_table("usuarios", [make_column("id", "int64")], pk_columns=["id"])
    assert kafka_key(table, {"id": 7}) == "7"


def test_kafka_key_composite_pk_is_json_array() -> None:
    table = make_table(
        "pedido_itens",
        [make_column("pedido_id", "int64"), make_column("produto_id", "int64")],
        pk_columns=["pedido_id", "produto_id"],
    )
    assert kafka_key(table, {"pedido_id": 1, "produto_id": 2}) == "[1, 2]"


def test_open_configures_idempotent_producer(fake_kafka: dict[str, object]) -> None:
    table = make_table("usuarios", [make_column("id", "int64")])
    sink = KafkaSink({"bootstrap_servers": "kafka:9092", "schema_registry_url": "http://sr:8081"})

    sink.open(make_run_context("/out"), table, pa.schema([("id", pa.int64())]))

    producer = fake_kafka["producer"]
    assert isinstance(producer, FakeProducer)
    assert producer.config["enable.idempotence"] is True
    assert producer.config["acks"] == "all"
    assert producer.config["compression.type"] == "zstd"
    assert producer.config["linger.ms"] == 20


def test_topic_uses_prefix_and_table_name(fake_kafka: dict[str, object]) -> None:
    table = make_table("usuarios", [make_column("id", "int64")])
    sink = KafkaSink({"topic_prefix": "loja."})
    sink.open(make_run_context("/out"), table, pa.schema([("id", pa.int64())]))

    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1])], schema=schema)
    receipt = sink.write_chunk(1, batch)

    assert "loja.usuarios" in receipt.sink_ref


def test_write_chunk_succeeds_only_after_all_deliveries_ok(fake_kafka: dict[str, object]) -> None:
    table = make_table("usuarios", [make_column("id", "int64")])
    sink = KafkaSink()
    sink.open(make_run_context("/out"), table, pa.schema([("id", pa.int64())]))
    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1, 2, 3])], schema=schema)

    sink.write_chunk(1, batch)

    producer = fake_kafka["producer"]
    assert isinstance(producer, FakeProducer)
    assert producer.flush_calls == 1
    assert [msg["key"] for msg in producer.produced] == ["1", "2", "3"]


def test_write_chunk_fails_when_any_delivery_report_has_error(
    fake_kafka: dict[str, object],
) -> None:
    table = make_table("usuarios", [make_column("id", "int64")])
    sink = KafkaSink()
    sink.open(make_run_context("/out"), table, pa.schema([("id", pa.int64())]))
    producer = fake_kafka["producer"]
    assert isinstance(producer, FakeProducer)
    producer.fail_next_delivery = True

    schema = pa.schema([("id", pa.int64())])
    batch = pa.record_batch([pa.array([1])], schema=schema)

    with pytest.raises(SinkError):
        sink.write_chunk(1, batch)


def test_chunk_state_is_always_absent(fake_kafka: dict[str, object]) -> None:
    table = make_table("usuarios", [make_column("id", "int64")])
    sink = KafkaSink()
    sink.open(make_run_context("/out"), table, pa.schema([("id", pa.int64())]))

    assert sink.chunk_state(1) == "absent"
    assert sink.chunk_state(999) == "absent"
