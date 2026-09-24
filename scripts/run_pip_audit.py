"""Roda `pip-audit` sobre o `uv.lock` (base + extras + dev), com as exceções de §3.2.1."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from check_security_exceptions import (
    DEFAULT_PATH,
    check,
    load_raw_exceptions,
    parse_exceptions,
    pip_audit_ignore_args,
)


def main() -> int:
    errors = check(DEFAULT_PATH)
    if errors:
        for error in errors:
            print(f"security/exceptions.yaml: {error}", file=sys.stderr)
        return 1

    exceptions, _ = parse_exceptions(load_raw_exceptions(DEFAULT_PATH))
    export = subprocess.run(
        ["uv", "export", "--frozen", "--no-hashes", "--all-extras", "--no-emit-project"],
        check=True,
        capture_output=True,
        text=True,
    )
    ignore_args = pip_audit_ignore_args(exceptions)
    with tempfile.TemporaryDirectory() as tmp_dir:
        requirements_path = Path(tmp_dir) / "requirements.txt"
        requirements_path.write_text(export.stdout, encoding="utf-8")
        audit = subprocess.run(
            [
                "uv",
                "run",
                "pip-audit",
                "--strict",
                # `uv export` já resolveu a árvore de dependências inteira e travada
                # (uv.lock); pedir para o pip-audit resolver de novo via pip criaria
                # um venv efêmero desnecessário (e indisponível sem python3-venv).
                # `-r -` (stdin) não é aceito por esta versão do pip-audit, por isso
                # o arquivo temporário.
                "--disable-pip",
                "--no-deps",
                "-r",
                str(requirements_path),
                *ignore_args,
            ]
        )
    return audit.returncode


if __name__ == "__main__":
    raise SystemExit(main())
