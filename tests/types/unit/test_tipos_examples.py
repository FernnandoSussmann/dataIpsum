"""Os exemplos de `examples/tipos/*.yaml` existem e validam (DD-01 A.9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dataipsum.schema.loader import load_schema, validate
from dataipsum.schema.models import ValidationContext

EXAMPLES_DIR = Path(__file__).parents[3] / "examples" / "tipos"


def _example_paths() -> list[Path]:
    return sorted(EXAMPLES_DIR.glob("*.yaml"))


def test_existem_exemplos_obrigatorios() -> None:
    esperados = {
        "todos-os-tipos.yaml",
        "nulos.yaml",
        "documentos-invalidos.yaml",
        "email-enderecos.yaml",
        "formatacao.yaml",
        "cartoes-bandeiras.yaml",
        "locale-por-coluna.yaml",
    }
    assert esperados <= {path.name for path in _example_paths()}


def test_readme_existe() -> None:
    assert (EXAMPLES_DIR / "README.md").is_file()


@pytest.mark.parametrize("path", _example_paths(), ids=lambda path: path.name)
def test_exemplo_valida(path: Path, registry) -> None:
    generators = {name: registry.get_generator(name)() for name in registry.generators}
    schema = load_schema(path)
    report = validate(schema, ValidationContext(generators=generators))
    assert report.is_valid, report.errors
