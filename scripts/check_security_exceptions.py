"""Valida `security/exceptions.yaml` e traduz exceções em argumentos por ferramenta.

DD-00 §3.2.1.
"""

from __future__ import annotations

import argparse
import re
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


_NOSEC_PATTERN = re.compile(r"#\s*nosec\b(?:\s+([A-Za-z0-9_,\s]+))?")
_NOSEMGREP_PATTERN = re.compile(r"#\s*nosemgrep\b(?::\s*([\w,\s-]+))?")


def _registered_ids(exceptions: list[SecurityException], tool: str) -> frozenset[str]:
    return frozenset(exception.id for exception in exceptions if exception.tool == tool)


def _unregistered_ids_on_line(
    path: Path,
    line_number: int,
    line: str,
    label: str,
    pattern: re.Pattern[str],
    registered: frozenset[str],
) -> list[str]:
    match = pattern.search(line)
    if match is None:
        return []
    ids = [part.strip() for part in (match.group(1) or "").split(",") if part.strip()]
    if not ids:
        return [f"{path}:{line_number}: '# {label}' sem ID — não casa com exceção registrada"]
    return [
        f"{path}:{line_number}: '# {label} {found_id}' sem entrada correspondente em "
        "security/exceptions.yaml"
        for found_id in ids
        if found_id not in registered
    ]


def find_unregistered_suppressions(src_dir: Path, exceptions: list[SecurityException]) -> list[str]:
    """`# nosec`/`# nosemgrep` sem exceção registrada correspondente (DD-00 §3.2.1, "Proibido").

    Varredura textual simples (como `test_architecture_no_random.py` faz para
    `random`), não um parser de comentários real: um `# nosec` dentro de uma
    string literal geraria um falso positivo. Não há esse caso hoje em `src/`.
    """
    bandit_ids = _registered_ids(exceptions, "bandit")
    semgrep_ids = _registered_ids(exceptions, "semgrep")
    violations: list[str] = []
    for path in sorted(src_dir.rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            violations += _unregistered_ids_on_line(
                path, line_number, line, "nosec", _NOSEC_PATTERN, bandit_ids
            )
            violations += _unregistered_ids_on_line(
                path, line_number, line, "nosemgrep", _NOSEMGREP_PATTERN, semgrep_ids
            )
    return violations


def check(
    path: Path = DEFAULT_PATH, *, today: date | None = None, src_dir: Path | None = None
) -> list[str]:
    """`src_dir`, quando informado, também roda `find_unregistered_suppressions`.

    Fica fora do padrão (`None`) para não acoplar a validação do arquivo de
    exceções (testável com qualquer `path` isolado, ex. um `tmp_path`) a uma
    árvore `src/` fixa; `main()` passa `Path("src")` explicitamente.
    """
    today = today or date.today()
    raw_exceptions = load_raw_exceptions(path)
    exceptions, errors = parse_exceptions(raw_exceptions)
    expired = find_expired(exceptions, today)
    errors.extend(
        f"exceção expirada: '{exception.id}' (venceu em {exception.expires})"
        for exception in expired
    )
    if src_dir is not None and src_dir.exists():
        errors.extend(find_unregistered_suppressions(src_dir, exceptions))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--src-dir", type=Path, default=Path("src"))
    args = parser.parse_args()

    errors = check(args.path, src_dir=args.src_dir)
    for error in errors:
        print(f"security/exceptions.yaml: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
