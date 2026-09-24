"""Fakes de teste do DD-00 (§3.11): permitem que cada trilha teste sem as outras."""

from dataipsum.testing.fakes import (
    FakeExecutor,
    FakeLLM,
    FakePlanner,
    FakeSink,
    FakeToxicity,
    SchemaBuilder,
)

__all__ = [
    "FakeExecutor",
    "FakeLLM",
    "FakePlanner",
    "FakeSink",
    "FakeToxicity",
    "SchemaBuilder",
]
