"""Roda `pip-audit` sobre o `uv.lock` (base + extras + dev), com as exceções de §3.2.1."""

from __future__ import annotations

import subprocess
import sys

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
        ["uv", "export", "--frozen", "--no-hashes", "--all-extras"],
        check=True,
        capture_output=True,
        text=True,
    )
    ignore_args = pip_audit_ignore_args(exceptions)
    audit = subprocess.run(
        ["uv", "run", "pip-audit", "--strict", "-r", "-", *ignore_args],
        input=export.stdout,
        text=True,
    )
    return audit.returncode


if __name__ == "__main__":
    raise SystemExit(main())
