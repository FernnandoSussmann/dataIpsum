"""Padrões de código (DD-00 §3.10, §7.1 "padrões de código").

Roda o ruff isoladamente (`--isolated`, ignorando `pyproject.toml` — inclusive
o `per-file-ignores` que existe só para não quebrar o gate principal com estas
fixtures propositalmente ruins) sobre fixtures em
`tests/core/fixtures/code_standards/`, com o mesmo conjunto de regras que o
projeto liga (§3.10 "Como é verificado").
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "code_standards"
PYPROJECT_PATH = Path(__file__).parents[3] / "pyproject.toml"
REQUIRED_RULES = ("C4", "PERF", "SIM", "FURB", "N", "E741", "ERA", "RET")


def _ruff_check(fixture: Path) -> list[dict[str, object]]:
    result = subprocess.run(
        [
            "uv",
            "run",
            "ruff",
            "check",
            "--isolated",
            "--select",
            ",".join((*REQUIRED_RULES, "UP", "I", "E", "F", "W")),
            "--output-format=json",
            str(fixture),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return list(json.loads(result.stdout))


def test_loop_com_append_reprova_perf401() -> None:
    codes = {violation["code"] for violation in _ruff_check(FIXTURES_DIR / "violacoes.py")}
    assert "PERF401" in codes


def test_codigo_comentado_reprova_era001() -> None:
    codes = {violation["code"] for violation in _ruff_check(FIXTURES_DIR / "violacoes.py")}
    assert "ERA001" in codes


def test_nome_ambiguo_reprova_e741() -> None:
    codes = {violation["code"] for violation in _ruff_check(FIXTURES_DIR / "violacoes.py")}
    assert "E741" in codes


def test_nome_fora_do_padrao_reprova_n802() -> None:
    codes = {violation["code"] for violation in _ruff_check(FIXTURES_DIR / "violacoes.py")}
    assert "N802" in codes


def test_versao_funcional_e_bem_nomeada_passa() -> None:
    assert _ruff_check(FIXTURES_DIR / "conformes.py") == []


def _is_selected(rule: str, selected: list[str]) -> bool:
    return any(rule.startswith(code) for code in selected)


def test_pyproject_nao_desliga_nenhuma_regra_da_secao_3_10() -> None:
    config = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    lint_config = config["tool"]["ruff"]["lint"]
    ignored = set(lint_config.get("ignore", []))
    assert ignored.isdisjoint(REQUIRED_RULES)
    selected = lint_config["select"]
    assert all(_is_selected(rule, selected) for rule in REQUIRED_RULES)
