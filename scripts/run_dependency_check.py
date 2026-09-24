"""Roda OWASP Dependency-Check no `uv.lock` (pre-push/CI, DD-00 §3.2.1)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DEPENDENCY_CHECK_IMAGE = "owasp/dependency-check:10.0.4"
FAIL_ON_CVSS = "7"


def main() -> int:
    api_key = os.environ.get("NVD_API_KEY")
    if not api_key:
        print(
            "NVD_API_KEY não definida. Configure-a com uma chave da NVD "
            "(https://nvd.nist.gov/developers/request-an-api-key) antes de rodar "
            "o hook de pre-push ou a CI. O Dependency-Check nunca passa em silêncio.",
            file=sys.stderr,
        )
        return 1

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
        ],
        check=False,
    )
    requirements_path.unlink(missing_ok=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
