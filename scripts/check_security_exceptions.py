"""Valida `security/exceptions.yaml` e traduz exceções em argumentos por ferramenta.

DD-00 §3.2.1.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

DEFAULT_PATH = Path("security/exceptions.yaml")
REQUIRED_FIELDS = ("id", "tool", "justification", "owner", "expires")
KNOWN_TOOLS = frozenset({"bandit", "semgrep", "pip-audit", "dependency-check"})


@dataclass(frozen=True)
class SecurityException:
    id: str
    tool: str
    justification: str
    owner: str
    expires: date


def load_raw_exceptions(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return content.get("exceptions", []) or []


def parse_exceptions(
    raw_exceptions: list[dict[str, object]],
) -> tuple[list[SecurityException], list[str]]:
    parsed: list[SecurityException] = []
    errors: list[str] = []
    for index, entry in enumerate(raw_exceptions):
        entry_errors = _validate_entry(index, entry)
        if entry_errors:
            errors.extend(entry_errors)
            continue
        parsed.append(
            SecurityException(
                id=str(entry["id"]),
                tool=str(entry["tool"]),
                justification=str(entry["justification"]),
                owner=str(entry["owner"]),
                expires=_parse_date(entry["expires"]),
            )
        )
    return parsed, errors


def _validate_entry(index: int, entry: dict[str, object]) -> list[str]:
    missing = [field for field in REQUIRED_FIELDS if not entry.get(field)]
    errors = [f"exceptions[{index}]: campo obrigatório ausente: '{field}'" for field in missing]
    if "tool" in entry and entry["tool"] not in KNOWN_TOOLS and not missing:
        errors.append(f"exceptions[{index}]: ferramenta desconhecida: '{entry['tool']}'")
    return errors


def _parse_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def find_expired(exceptions: list[SecurityException], today: date) -> list[SecurityException]:
    return [exception for exception in exceptions if exception.expires < today]


def pip_audit_ignore_args(exceptions: list[SecurityException]) -> list[str]:
    ids = (exception.id for exception in exceptions if exception.tool == "pip-audit")
    return [arg for cve_id in ids for arg in ("--ignore-vuln", cve_id)]


def bandit_skip_ids(exceptions: list[SecurityException]) -> list[str]:
    return [exception.id for exception in exceptions if exception.tool == "bandit"]


def semgrep_exclude_rule_ids(exceptions: list[SecurityException]) -> list[str]:
    return [exception.id for exception in exceptions if exception.tool == "semgrep"]


def dependency_check_suppression_ids(exceptions: list[SecurityException]) -> list[str]:
    return [exception.id for exception in exceptions if exception.tool == "dependency-check"]


def check(path: Path = DEFAULT_PATH, *, today: date | None = None) -> list[str]:
    today = today or date.today()
    raw_exceptions = load_raw_exceptions(path)
    exceptions, errors = parse_exceptions(raw_exceptions)
    expired = find_expired(exceptions, today)
    errors.extend(
        f"exceção expirada: '{exception.id}' (venceu em {exception.expires})"
        for exception in expired
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()

    errors = check(args.path)
    for error in errors:
        print(f"security/exceptions.yaml: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
