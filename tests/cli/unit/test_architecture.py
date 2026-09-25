"""Teste de arquitetura (DD-02 §G.4, §G.6): a CLI só importa `dataipsum.api` e
`dataipsum.config` como boundary com as demais trilhas — nunca `types/`,
`relations/`, `llm/`, `execution/`, `sinks/` nem `schema_io/` diretamente."""

from __future__ import annotations

import ast
from pathlib import Path

import dataipsum.cli

_FORBIDDEN_MODULES = ("types", "relations", "llm", "execution", "sinks", "schema_io")


def _imported_module_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_cli_nao_importa_pacotes_de_trilha_diretamente() -> None:
    cli_dir = Path(dataipsum.cli.__file__).parent
    offending: dict[str, set[str]] = {}
    for path in cli_dir.glob("*.py"):
        imported = _imported_module_names(path.read_text(encoding="utf-8"))
        hits = {
            name
            for name in imported
            if any(
                name == f"dataipsum.{forbidden}" or name.startswith(f"dataipsum.{forbidden}.")
                for forbidden in _FORBIDDEN_MODULES
            )
        }
        if hits:
            offending[path.name] = hits
    assert not offending, f"imports proibidos na CLI: {offending}"
