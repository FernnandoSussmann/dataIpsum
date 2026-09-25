"""Monta o `Dockerfile` da raiz a partir de `docker/Dockerfile.in` e dos fragmentos por área
(DD-00 §3.12.2).

Cada trilha edita só o próprio par de fragmentos em `docker/fragments/<área>.{build,runtime}
.dockerfile`. Este script:

1. Valida cada fragmento (instruções proibidas, `apt-get install` seguro, compiladores fora do
   estágio final, nomes de `ENV`/`ARG` de segredo) ANTES de montar qualquer coisa.
2. Concatena os fragmentos, na ordem fixa `tipos, relacoes, llm, execucao, sinks, schema-io,
   cli-docker, contrato`, nos dois pontos de extensão do template (`# @fragments build` e
   `# @fragments runtime`).
3. Escreve o resultado em `Dockerfile` (modo padrão) ou só compara com o que já está lá
   (`--check`, usado pelo hook de pre-commit `dockerfile-render` e pela CI; não escreve nada).

Fragmentos vazios (sem nenhuma instrução real, só comentários/linhas em branco) não contribuem
com nada para o `Dockerfile` gerado: com todos os 16 fragmentos vazios, o resultado é
exatamente a imagem base do template.

Uso:
    uv run python scripts/render_dockerfile.py            # gera/atualiza o Dockerfile
    uv run python scripts/render_dockerfile.py --check    # só verifica, não escreve (exit != 0
                                                            # se o Dockerfile estiver divergente)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

AREAS: tuple[str, ...] = (
    "tipos",
    "relacoes",
    "llm",
    "execucao",
    "sinks",
    "schema-io",
    "cli-docker",
    "contrato",
)

STAGES: tuple[str, ...] = ("build", "runtime")

MARKER_BUILD = "# @fragments build"
MARKER_RUNTIME = "# @fragments runtime"

# Instruções nunca aceitas em fragmentos (mudariam a imagem base ou o entrypoint).
FORBIDDEN_INSTRUCTIONS = frozenset(
    {
        "FROM",
        "USER",
        "ENTRYPOINT",
        "CMD",
        "EXPOSE",
        "VOLUME",
        "SHELL",
        "HEALTHCHECK",
        "ADD",
    }
)

# As únicas instruções aceitas em fragmentos (§3.12.2). Qualquer outra é rejeitada, mesmo que
# não conste explicitamente na lista de proibidas acima (ex.: WORKDIR, STOPSIGNAL, ONBUILD).
ALLOWED_INSTRUCTIONS = frozenset({"ARG", "ENV", "RUN", "COPY", "LABEL"})

_SECRET_NAME_RE = re.compile(r"pass|secret|token|key", re.IGNORECASE)

# Nomes de compilador proibidos no estágio final (busca por palavra inteira).
_COMPILER_NAMES = ("gcc", "g++", "make", "build-essential")
_COMPILER_RE = re.compile(
    r"(?<![\w+-])(?:" + "|".join(re.escape(name) for name in _COMPILER_NAMES) + r")(?![\w+-])",
    re.IGNORECASE,
)


class FragmentError(Exception):
    """Fragmento inválido: instrução proibida, `apt-get` inseguro, compilador ou segredo."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _fragment_path(fragments_dir: Path, area: str, stage: str) -> Path:
    return fragments_dir / f"{area}.{stage}.dockerfile"


def _logical_instructions(text: str) -> list[str]:
    """Quebra o texto de um fragmento em instruções lógicas, juntando continuações de linha
    (`\\` no fim da linha) e ignorando linhas em branco e comentários (`#`)."""
    instructions: list[str] = []
    buffer: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not buffer and (not line.strip() or line.strip().startswith("#")):
            continue
        buffer.append(line)
        if line.endswith("\\"):
            continue
        instructions.append("\n".join(buffer))
        buffer = []
    if buffer:
        instructions.append("\n".join(buffer))
    return instructions


def _instruction_keyword(instruction: str) -> str:
    first_line = instruction.splitlines()[0].strip()
    return first_line.split(None, 1)[0].upper()


def _check_apt_get(fragment_name: str, instruction: str) -> None:
    if "apt-get install" not in instruction:
        return
    if "--no-install-recommends" not in instruction:
        raise FragmentError(
            f"{fragment_name}: 'RUN apt-get install' precisa de --no-install-recommends"
        )
    if "/var/lib/apt/lists" not in instruction:
        raise FragmentError(
            f"{fragment_name}: 'RUN apt-get install' precisa limpar /var/lib/apt/lists"
        )


def _check_compilers(fragment_name: str, instruction: str) -> None:
    match = _COMPILER_RE.search(instruction)
    if match:
        raise FragmentError(
            f"{fragment_name}: compilador '{match.group(0)}' é proibido no estágio final"
        )


def _env_or_arg_name(instruction: str) -> str:
    # "ENV NOME=valor outro=valor" ou legado "ENV NOME valor"; "ARG NOME" ou "ARG NOME=padrão".
    first_line = instruction.splitlines()[0].strip()
    _keyword, _, remainder = first_line.partition(" ")
    remainder = remainder.strip()
    first_token = remainder.split(None, 1)[0] if remainder else ""
    name, _, _ = first_token.partition("=")
    return name


def _check_secret_name(fragment_name: str, instruction: str, keyword: str) -> None:
    name = _env_or_arg_name(instruction)
    if not name:
        return
    if _SECRET_NAME_RE.search(name) and not name.lower().endswith("_env"):
        raise FragmentError(
            f"{fragment_name}: {keyword} '{name}' parece um segredo; use um nome terminado "
            "em '_env' (ele deve guardar só o NOME da variável de ambiente, nunca o valor)"
        )


def validate_fragment(fragment_name: str, stage: str, text: str) -> None:
    """Valida um fragmento. `fragment_name` é usado só nas mensagens de erro.

    Levanta `FragmentError` descrevendo o fragmento e a instrução ofensiva."""
    for instruction in _logical_instructions(text):
        keyword = _instruction_keyword(instruction)
        if keyword in FORBIDDEN_INSTRUCTIONS:
            raise FragmentError(
                f"{fragment_name}: instrução '{keyword}' não é permitida em fragmentos"
            )
        if keyword not in ALLOWED_INSTRUCTIONS:
            raise FragmentError(
                f"{fragment_name}: instrução '{keyword}' não está na lista permitida "
                f"({', '.join(sorted(ALLOWED_INSTRUCTIONS))})"
            )
        if keyword == "COPY" and not instruction.strip().startswith("COPY --from=build"):
            raise FragmentError(
                f"{fragment_name}: 'COPY' só é permitido como 'COPY --from=build ...'"
            )
        if keyword == "RUN":
            _check_apt_get(fragment_name, instruction)
            if stage == "runtime":
                _check_compilers(fragment_name, instruction)
        if keyword in ("ENV", "ARG"):
            _check_secret_name(fragment_name, instruction, keyword)


def _fragment_is_empty(text: str) -> bool:
    return not _logical_instructions(text)


def _read_fragment(fragments_dir: Path, area: str, stage: str) -> str:
    path = _fragment_path(fragments_dir, area, stage)
    if not path.is_file():
        raise FragmentError(f"fragmento ausente: {path}")
    return path.read_text(encoding="utf-8")


def _assembled_block(fragments_dir: Path, stage: str) -> str:
    """Valida e concatena os fragmentos de um estágio, na ordem fixa de `AREAS`.

    Fragmentos vazios (só comentários/linhas em branco) não contribuem em nada: com todas as
    áreas vazias, o retorno é a string vazia.
    """
    parts: list[str] = []
    for area in AREAS:
        name = f"{area}.{stage}.dockerfile"
        text = _read_fragment(fragments_dir, area, stage)
        validate_fragment(name, stage, text)
        if _fragment_is_empty(text):
            continue
        parts.append(f"# --- {name} ---\n{text.rstrip()}\n")
    return "\n".join(parts)


def render(template_text: str, fragments_dir: Path) -> str:
    """Monta o conteúdo final do Dockerfile a partir do template e dos fragmentos.

    Valida todos os 16 fragmentos antes de montar qualquer coisa.
    """
    build_block = _assembled_block(fragments_dir, "build")
    runtime_block = _assembled_block(fragments_dir, "runtime")

    out_lines: list[str] = []
    for line in template_text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        if stripped == MARKER_BUILD:
            if build_block:
                out_lines.append(build_block)
            continue
        if stripped == MARKER_RUNTIME:
            if runtime_block:
                out_lines.append(runtime_block)
            continue
        out_lines.append(line)
    return "".join(out_lines)


def main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "só verifica se o Dockerfile está atualizado; não escreve nada (exit != 0 se divergir)"
        ),
    )
    args = parser.parse_args(argv)

    root = repo_root if repo_root is not None else _repo_root()
    template_path = root / "docker" / "Dockerfile.in"
    fragments_dir = root / "docker" / "fragments"
    output_path = root / "Dockerfile"

    template_text = template_path.read_text(encoding="utf-8")

    try:
        rendered = render(template_text, fragments_dir)
    except FragmentError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    if args.check:
        current = output_path.read_text(encoding="utf-8") if output_path.is_file() else None
        if current != rendered:
            print(
                f"erro: {output_path} está desatualizado ou foi editado à mão. "
                "Rode `uv run python scripts/render_dockerfile.py` e faça commit do resultado.",
                file=sys.stderr,
            )
            return 1
        return 0

    output_path.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
