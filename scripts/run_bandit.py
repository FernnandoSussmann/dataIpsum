"""Roda `bandit` sobre `src`, com as exceções de §3.2.1 traduzidas para `--skip`."""

from __future__ import annotations

import subprocess
import sys

from check_security_exceptions import (
    DEFAULT_PATH,
    bandit_skip_ids,
    check,
    load_raw_exceptions,
    parse_exceptions,
)


def main() -> int:
    errors = check(DEFAULT_PATH)
    if errors:
        for error in errors:
            print(f"security/exceptions.yaml: {error}", file=sys.stderr)
        return 1

    exceptions, _ = parse_exceptions(load_raw_exceptions(DEFAULT_PATH))
    skip_ids = bandit_skip_ids(exceptions)
    # Uma exceção com `tool: bandit` também autoriza `# nosec <id>` inline
    # (DD-00 §3.2.1, "Proibido"). Quando o achado real já está resolvido só
    # por um `# nosec` pontual (caso de B506 hoje), este `--skip` global é
    # redundante mas inofensivo: não há outro uso do mesmo padrão em `src/`
    # que ele esconderia. Reavaliar se isso deixar de ser verdade.
    skip_args = ["--skip", ",".join(skip_ids)] if skip_ids else []
    result = subprocess.run(
        ["uv", "run", "bandit", "-r", "src", "-c", "pyproject.toml", "-ll", *skip_args]
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
