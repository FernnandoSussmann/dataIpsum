"""Testes de `.pre-commit-config.yaml` e do detector de `# nosec`/`# nosemgrep`
sem exceção registrada (DD-00 §3.2.1, §7.1 "pre-commit e segurança").

Os testes com bandit/semgrep vulneráveis usam só bandit (sem rede) — os
unitários não podem depender de rede (§3.2), e semgrep baixa as regras do
registry a cada chamada.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml
from check_security_exceptions import (
    DEFAULT_PATH,
    SecurityException,
    check,
    find_unregistered_suppressions,
    load_raw_exceptions,
    parse_exceptions,
)

REPO_ROOT = Path(__file__).parents[3]
PRECOMMIT_CONFIG_PATH = REPO_ROOT / ".pre-commit-config.yaml"
SECURITY_FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "security"

PRE_COMMIT_STAGE_HOOK_IDS = {
    "ruff-check",
    "ruff-format",
    "mypy",
    "pytest-unit",
    "bandit",
    "semgrep",
    "pip-audit",
    "security-exceptions",
    "dockerfile-render",
}
PRE_PUSH_STAGE_HOOK_IDS = {"pytest-integration", "owasp-dependency-check"}
THIRD_PARTY_REPOS = {
    "https://github.com/gitleaks/gitleaks": "gitleaks",
    "https://github.com/AleksaC/hadolint-py": "hadolint",
}


@pytest.fixture(scope="module")
def precommit_config() -> dict[str, object]:
    return yaml.safe_load(PRECOMMIT_CONFIG_PATH.read_text(encoding="utf-8"))


def _local_hooks(precommit_config: dict[str, object]) -> dict[str, dict[str, object]]:
    for repo in precommit_config["repos"]:
        if repo["repo"] == "local":
            return {hook["id"]: hook for hook in repo["hooks"]}
    raise AssertionError("repo 'local' não encontrado em .pre-commit-config.yaml")


def _third_party_repos(precommit_config: dict[str, object]) -> list[dict[str, object]]:
    return [repo for repo in precommit_config["repos"] if repo["repo"] != "local"]


def test_todos_os_hooks_locais_esperados_existem(precommit_config: dict[str, object]) -> None:
    hooks = _local_hooks(precommit_config)
    assert set(hooks) == PRE_COMMIT_STAGE_HOOK_IDS | PRE_PUSH_STAGE_HOOK_IDS


def test_hooks_locais_usam_language_system_e_uv_run(
    precommit_config: dict[str, object],
) -> None:
    for hook_id, hook in _local_hooks(precommit_config).items():
        assert hook["language"] == "system", hook_id
        assert "uv run" in hook["entry"], hook_id


def test_hooks_pre_commit_no_estagio_certo(precommit_config: dict[str, object]) -> None:
    hooks = _local_hooks(precommit_config)
    actual = {hook_id for hook_id, hook in hooks.items() if hook.get("stages") == ["pre-commit"]}
    assert actual == PRE_COMMIT_STAGE_HOOK_IDS


def test_hooks_pre_push_no_estagio_certo(precommit_config: dict[str, object]) -> None:
    hooks = _local_hooks(precommit_config)
    actual = {hook_id for hook_id, hook in hooks.items() if hook.get("stages") == ["pre-push"]}
    assert actual == PRE_PUSH_STAGE_HOOK_IDS


def test_hooks_de_terceiros_tem_rev_fixo_e_estagio_pre_commit(
    precommit_config: dict[str, object],
) -> None:
    repos = _third_party_repos(precommit_config)
    assert {repo["repo"] for repo in repos} == set(THIRD_PARTY_REPOS)
    for repo in repos:
        assert repo.get("rev"), f"{repo['repo']} sem rev fixo"
        expected_id = THIRD_PARTY_REPOS[repo["repo"]]
        hook_ids = {hook["id"] for hook in repo["hooks"]}
        assert expected_id in hook_ids
        for hook in repo["hooks"]:
            assert hook.get("stages") == ["pre-commit"], hook["id"]


# --- detector de `# nosec`/`# nosemgrep` sem exceção registrada -------------


def test_sem_id_e_marcado_como_nao_registrado(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text("x = 1  # nosec\n", encoding="utf-8")
    violations = find_unregistered_suppressions(src_dir, [])
    assert any("sem ID" in violation for violation in violations)


def test_id_sem_excecao_registrada_e_marcado(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text("x = 1  # nosec B999\n", encoding="utf-8")
    violations = find_unregistered_suppressions(src_dir, [])
    assert any("B999" in violation for violation in violations)


def test_id_com_excecao_registrada_nao_e_marcado(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text("x = 1  # nosec B999\n", encoding="utf-8")
    exception = SecurityException(
        id="B999", tool="bandit", justification="ok", owner="alguem", expires=date(2999, 1, 1)
    )
    assert find_unregistered_suppressions(src_dir, [exception]) == []


def test_nosemgrep_sem_excecao_e_marcado(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text("x = 1  # nosemgrep: some-rule-id\n", encoding="utf-8")
    violations = find_unregistered_suppressions(src_dir, [])
    assert any("some-rule-id" in violation for violation in violations)


def test_src_real_do_projeto_nao_tem_suppressoes_nao_registradas() -> None:
    assert check(DEFAULT_PATH, src_dir=REPO_ROOT / "src") == []


def test_nosec_b506_real_esta_registrado() -> None:
    exceptions, _ = parse_exceptions(load_raw_exceptions(DEFAULT_PATH))
    assert any(exception.id == "B506" and exception.tool == "bandit" for exception in exceptions)


# --- fixtures com vulnerabilidade conhecida ---------------------------------


def _bandit_test_ids(fixture: Path) -> set[str]:
    result = subprocess.run(
        ["uv", "run", "bandit", str(fixture), "-f", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {finding["test_id"] for finding in json.loads(result.stdout)["results"]}


def test_subprocess_shell_true_reprovado_pelo_bandit() -> None:
    ids = _bandit_test_ids(SECURITY_FIXTURES_DIR / "subprocess_shell_true.py")
    assert "B602" in ids


def test_yaml_load_sem_safeloader_reprovado_pelo_bandit() -> None:
    ids = _bandit_test_ids(SECURITY_FIXTURES_DIR / "yaml_load_unsafe.py")
    assert "B506" in ids
