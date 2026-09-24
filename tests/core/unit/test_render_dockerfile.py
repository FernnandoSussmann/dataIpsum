"""Testes do validador/montador de fragmentos da imagem Docker (DD-00 §3.12.2, §7.1).

Rápido, sem Docker: exercita `render_dockerfile.py` diretamente (não constrói nenhuma imagem).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from render_dockerfile import AREAS, FragmentError, main, render, validate_fragment

TEMPLATE = (
    "FROM python:3.12-slim@sha256:deadbeef AS build\n"
    "# @fragments build\n"
    "FROM python:3.12-slim@sha256:deadbeef AS final\n"
    "# @fragments runtime\n"
    "USER 10001\n"
)


def _write_empty_fragments(fragments_dir: Path) -> None:
    fragments_dir.mkdir(parents=True, exist_ok=True)
    for area in AREAS:
        for stage in ("build", "runtime"):
            (fragments_dir / f"{area}.{stage}.dockerfile").write_text(
                f"# {area} {stage}: vazio.\n", encoding="utf-8"
            )


def _make_repo(tmp_path: Path) -> Path:
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker" / "Dockerfile.in").write_text(TEMPLATE, encoding="utf-8")
    _write_empty_fragments(tmp_path / "docker" / "fragments")
    return tmp_path


def test_ordem_das_areas_e_fixa() -> None:
    assert AREAS == (
        "tipos",
        "relacoes",
        "llm",
        "execucao",
        "sinks",
        "schema-io",
        "cli-docker",
        "contrato",
    )


def test_fragmentos_vazios_geram_exatamente_a_imagem_base(tmp_path: Path) -> None:
    fragments_dir = tmp_path / "fragments"
    _write_empty_fragments(fragments_dir)

    assert render(TEMPLATE, fragments_dir) == (
        "FROM python:3.12-slim@sha256:deadbeef AS build\n"
        "FROM python:3.12-slim@sha256:deadbeef AS final\n"
        "USER 10001\n"
    )


@pytest.mark.parametrize(
    "instruction",
    [
        "FROM scratch",
        "USER root",
        'ENTRYPOINT ["sh"]',
        'CMD ["sh"]',
        "EXPOSE 8080",
        'VOLUME ["/x"]',
        'SHELL ["/bin/sh"]',
        "HEALTHCHECK CMD true",
        "ADD x /x",
    ],
)
def test_instrucao_proibida_e_rejeitada(instruction: str) -> None:
    with pytest.raises(FragmentError):
        validate_fragment("area.build.dockerfile", "build", instruction + "\n")


def test_instrucao_fora_da_lista_permitida_e_rejeitada() -> None:
    with pytest.raises(FragmentError):
        validate_fragment("area.build.dockerfile", "build", "WORKDIR /outro\n")


def test_apt_get_sem_no_install_recommends_e_rejeitado() -> None:
    with pytest.raises(FragmentError, match="no-install-recommends"):
        validate_fragment(
            "area.build.dockerfile",
            "build",
            "RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*\n",
        )


def test_apt_get_sem_limpeza_e_rejeitado() -> None:
    with pytest.raises(FragmentError, match="apt/lists"):
        validate_fragment(
            "area.build.dockerfile",
            "build",
            "RUN apt-get update && apt-get install -y --no-install-recommends curl\n",
        )


def test_apt_get_correto_e_aceito() -> None:
    validate_fragment(
        "area.build.dockerfile",
        "build",
        "RUN apt-get update && apt-get install -y --no-install-recommends curl "
        "&& rm -rf /var/lib/apt/lists/*\n",
    )


def test_compilador_no_estagio_final_e_rejeitado() -> None:
    with pytest.raises(FragmentError, match="gcc"):
        validate_fragment("llm.runtime.dockerfile", "runtime", "RUN gcc --version\n")


def test_compilador_no_estagio_build_e_aceito() -> None:
    validate_fragment("llm.build.dockerfile", "build", "RUN gcc --version\n")


def test_env_api_key_e_rejeitado() -> None:
    with pytest.raises(FragmentError, match="_env"):
        validate_fragment("llm.build.dockerfile", "build", "ENV API_KEY=sk-123\n")


def test_env_x_api_key_env_e_aceito() -> None:
    validate_fragment("llm.build.dockerfile", "build", "ENV X_API_KEY_ENV=nome-da-var\n")


def test_arg_secret_sem_sufixo_env_e_rejeitado() -> None:
    with pytest.raises(FragmentError):
        validate_fragment("area.build.dockerfile", "build", "ARG DB_PASSWORD=hunter2\n")


def test_copy_sem_from_build_e_rejeitado() -> None:
    with pytest.raises(FragmentError, match="from=build"):
        validate_fragment("area.runtime.dockerfile", "runtime", "COPY x /x\n")


def test_copy_from_build_e_aceito() -> None:
    validate_fragment("area.runtime.dockerfile", "runtime", "COPY --from=build /app/.venv/x /x\n")


def test_check_falha_sem_dockerfile_gerado(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    assert main(["--check"], repo_root=root) != 0


def test_check_passa_com_dockerfile_atualizado(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    assert main([], repo_root=root) == 0
    assert main(["--check"], repo_root=root) == 0


def test_check_detecta_dockerfile_editado_a_mao(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    assert main([], repo_root=root) == 0
    (root / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    assert main(["--check"], repo_root=root) != 0


def test_main_rejeita_fragmento_com_instrucao_proibida(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _make_repo(tmp_path)
    (root / "docker" / "fragments" / "llm.runtime.dockerfile").write_text(
        "USER root\n", encoding="utf-8"
    )
    assert main([], repo_root=root) != 0
    assert "USER" in capsys.readouterr().err
