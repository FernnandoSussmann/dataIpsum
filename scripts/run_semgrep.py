"""Roda `semgrep` sobre `src`, com as exceções de §3.2.1 traduzidas para `--exclude-rule`."""

from __future__ import annotations

import subprocess
import sys

from check_security_exceptions import (
    DEFAULT_PATH,
    check,
    load_raw_exceptions,
    parse_exceptions,
    semgrep_exclude_rule_ids,
)


def main() -> int:
    errors = check(DEFAULT_PATH)
    if errors:
        for error in errors:
            print(f"security/exceptions.yaml: {error}", file=sys.stderr)
        return 1

    exceptions, _ = parse_exceptions(load_raw_exceptions(DEFAULT_PATH))
    exclude_args = [
        arg
        for rule_id in semgrep_exclude_rule_ids(exceptions)
        for arg in ("--exclude-rule", rule_id)
    ]
    result = subprocess.run(
        [
            "uv",
            "run",
            "semgrep",
            "scan",
            "--config",
            "p/owasp-top-ten",
            "--config",
            "p/python",
            "--error",
            "--metrics=off",
            *exclude_args,
            "src",
        ]
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
