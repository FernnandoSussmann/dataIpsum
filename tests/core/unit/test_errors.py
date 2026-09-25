"""Testes da hierarquia de erros (DD-00 §3.9)."""

from __future__ import annotations

from dataipsum.errors import (
    DataIpsumError,
    LLMError,
    ManifestError,
    ManifestMismatchError,
    ProviderRateLimited,
    SchemaError,
    ValidationError,
)


def test_schema_error_agrega_mensagens_com_caminho() -> None:
    error = SchemaError(
        [
            ValidationError(path="tables[0].name", message="identificador inválido"),
            ValidationError(path="tables[0].columns[1].max_length", message="obrigatório"),
        ]
    )
    assert "tables[0].name: identificador inválido" in str(error)
    assert error.errors[1].path == "tables[0].columns[1].max_length"


def test_hierarquia_deriva_de_data_ipsum_error() -> None:
    assert issubclass(SchemaError, DataIpsumError)
    assert issubclass(ManifestMismatchError, ManifestError)
    assert issubclass(ManifestError, DataIpsumError)
    assert issubclass(ProviderRateLimited, LLMError)
    assert issubclass(LLMError, DataIpsumError)
