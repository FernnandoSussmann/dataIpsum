"""Trilha E (DD-02): sinks de saída (parquet, csv, jsonl, postgres, mysql, kafka, ...)."""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from typing import cast

from dataipsum.errors import SinkError
from dataipsum.registry import Registry

_OPTIONAL_SINKS: tuple[tuple[str, str, str, str], ...] = (
    ("postgres", "psycopg", "dataipsum.sinks.postgres_sink", "PostgresSink"),
    ("mysql", "pymysql", "dataipsum.sinks.mysql_sink", "MysqlSink"),
    ("kafka", "confluent_kafka", "dataipsum.sinks.kafka_sink", "KafkaSink"),
)


def register(registry: Registry) -> None:
    """Registra os sinks de arquivo (`csv`, `json`, `jsonl`, `parquet`) sempre, e os
    sinks de banco/Kafka (`postgres`, `mysql`, `kafka`) só quando o extra
    correspondente está instalado (E.4). Sem o extra, o nome ainda é registrado, mas
    aponta para uma classe que recusa a construção com uma mensagem de instalação
    clara — assim `registry.get_sink("postgres")` nunca falha com "sink
    desconhecido" para um formato que existe, só ainda não está instalável.
    """
    from dataipsum.sinks.csv_sink import CsvSink
    from dataipsum.sinks.json_sink import JsonlSink, JsonSink
    from dataipsum.sinks.parquet_sink import ParquetSink

    registry.register_sink("csv", CsvSink)
    registry.register_sink("json", JsonSink)
    registry.register_sink("jsonl", JsonlSink)
    registry.register_sink("parquet", ParquetSink)

    for sink_name, extra_module, sink_module_path, class_name in _OPTIONAL_SINKS:
        registry.register_sink(
            sink_name,
            _resolve_optional_sink(sink_name, extra_module, sink_module_path, class_name),
        )


def _resolve_optional_sink(
    sink_name: str, extra_module: str, sink_module_path: str, class_name: str
) -> type:
    """`sink_name` dobra como o nome do extra em `pyproject.toml` (`postgres`,
    `mysql`, `kafka` são, ao mesmo tempo, o nome do sink e do extra que o traz)."""
    if importlib.util.find_spec(extra_module) is None:
        return _missing_extra_sink(sink_name)
    module = importlib.import_module(sink_module_path)
    return cast(type, getattr(module, class_name))


def _missing_extra_sink(extra_name: str) -> type:
    sink_name = extra_name
    install_hint = (
        f"o sink '{sink_name}' exige o extra opcional '{extra_name}': "
        f"instale com 'pip install dataipsum[{extra_name}]' "
        f"(ou 'uv sync --extra {extra_name}')."
    )

    class _MissingExtraSink:
        def __init__(self, options: Mapping[str, object] | None = None) -> None:
            raise SinkError(install_hint)

    _MissingExtraSink.__name__ = f"Missing{sink_name.capitalize()}Sink"
    _MissingExtraSink.__qualname__ = _MissingExtraSink.__name__
    return _MissingExtraSink
