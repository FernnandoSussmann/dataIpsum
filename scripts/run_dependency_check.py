"""Roda OWASP Dependency-Check no `uv.lock` (pre-push/CI, DD-00 §3.2.1)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from check_security_exceptions import (
    DEFAULT_PATH,
    check,
    dependency_check_suppression_ids,
    load_raw_exceptions,
    parse_exceptions,
)

DEPENDENCY_CHECK_IMAGE = "owasp/dependency-check:10.0.4"
FAIL_ON_CVSS = "7"
SUPPRESSION_PATH = Path("dependency-check-suppressions.xml")


def _suppression_entry(finding_id: str) -> str:
    tag = "cve" if finding_id.upper().startswith("CVE-") else "vulnerabilityName"
    return f"   <suppress>\n      <{tag}>{finding_id}</{tag}>\n   </suppress>"


def _write_suppression_file(finding_ids: list[str]) -> None:
    entries = "\n".join(_suppression_entry(finding_id) for finding_id in finding_ids)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<suppressions xmlns="https://jeremylong.github.io/DependencyCheck/'
        'dependency-suppression.1.3.xsd">\n'
        f"{entries}\n"
        "</suppressions>\n"
    )
    SUPPRESSION_PATH.write_text(xml, encoding="utf-8")


def main() -> int:
    errors = check(DEFAULT_PATH)
    if errors:
        for error in errors:
            print(f"security/exceptions.yaml: {error}", file=sys.stderr)
        return 1

    api_key = os.environ.get("NVD_API_KEY")
    if not api_key:
        print(
            "NVD_API_KEY não definida. Configure-a com uma chave da NVD "
            "(https://nvd.nist.gov/developers/request-an-api-key) antes de rodar "
            "o hook de pre-push ou a CI. O Dependency-Check nunca passa em silêncio.",
            file=sys.stderr,
        )
        return 1

    exceptions, _ = parse_exceptions(load_raw_exceptions(DEFAULT_PATH))
    suppression_ids = dependency_check_suppression_ids(exceptions)
    suppression_args: list[str] = []
    if suppression_ids:
        _write_suppression_file(suppression_ids)
        suppression_args = ["--suppression", "/src/dependency-check-suppressions.xml"]

    export = subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--all-extras"],
        check=True,
        capture_output=True,
        text=True,
    )
    requirements_path = Path("requirements-export.txt")
    requirements_path.write_text(export.stdout, encoding="utf-8")

    project_root = Path.cwd().resolve()
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            f"NVD_API_KEY={api_key}",
            "-v",
            f"{project_root}:/src",
            DEPENDENCY_CHECK_IMAGE,
            "--scan",
            "/src/requirements-export.txt",
            "--scan",
            "/src/uv.lock",
            "--project",
            "dataipsum",
            "--failOnCVSS",
            FAIL_ON_CVSS,
            "--out",
            "/src/.dependency-check",
            *suppression_args,
        ],
        check=False,
    )
    requirements_path.unlink(missing_ok=True)
    if suppression_ids:
        SUPPRESSION_PATH.unlink(missing_ok=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
