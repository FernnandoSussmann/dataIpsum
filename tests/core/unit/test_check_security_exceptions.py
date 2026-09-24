"""Testes do validador de `security/exceptions.yaml` (DD-00 §3.2.1, §7.1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from check_security_exceptions import (
    check,
    dependency_check_suppression_ids,
    parse_exceptions,
    pip_audit_ignore_args,
)

VALID_ENTRY = {
    "id": "CVE-2024-00000",
    "tool": "pip-audit",
    "justification": "falso positivo",
    "owner": "fernando",
    "expires": "2999-12-31",
}


def test_entrada_valida_nao_gera_erro() -> None:
    exceptions, errors = parse_exceptions([VALID_ENTRY])
    assert errors == []
    assert exceptions[0].id == "CVE-2024-00000"


def test_rejeita_sem_justificativa() -> None:
    entry = {**VALID_ENTRY, "justification": ""}
    _, errors = parse_exceptions([entry])
    assert any("justification" in error for error in errors)


def test_rejeita_sem_responsavel() -> None:
    entry = {**VALID_ENTRY, "owner": ""}
    _, errors = parse_exceptions([entry])
    assert any("owner" in error for error in errors)


def test_rejeita_ferramenta_desconhecida() -> None:
    entry = {**VALID_ENTRY, "tool": "eslint"}
    _, errors = parse_exceptions([entry])
    assert any("desconhecida" in error for error in errors)


def test_exceção_vencida_reprova(tmp_path: Path) -> None:
    expired_entry = {**VALID_ENTRY, "expires": "2000-01-01"}
    yaml_path = tmp_path / "exceptions.yaml"
    yaml_path.write_text(
        "exceptions:\n"
        f"  - id: {expired_entry['id']}\n"
        f"    tool: {expired_entry['tool']}\n"
        f"    justification: {expired_entry['justification']}\n"
        f"    owner: {expired_entry['owner']}\n"
        f'    expires: "{expired_entry["expires"]}"\n',
        encoding="utf-8",
    )
    errors = check(yaml_path, today=date(2026, 1, 1))
    assert any("vencida" in error or "expirada" in error for error in errors)


def test_arquivo_ausente_nao_gera_erro(tmp_path: Path) -> None:
    assert check(tmp_path / "nao-existe.yaml") == []


def test_pip_audit_ignore_args_filtra_por_ferramenta() -> None:
    bandit_entry = {**VALID_ENTRY, "id": "RULE-1", "tool": "bandit"}
    exceptions, _ = parse_exceptions([VALID_ENTRY, bandit_entry])
    assert pip_audit_ignore_args(exceptions) == ["--ignore-vuln", "CVE-2024-00000"]


def test_dependency_check_suppression_ids_filtra_por_ferramenta() -> None:
    entry = {**VALID_ENTRY, "id": "CVE-9999", "tool": "dependency-check"}
    exceptions, _ = parse_exceptions([VALID_ENTRY, entry])
    assert dependency_check_suppression_ids(exceptions) == ["CVE-9999"]
