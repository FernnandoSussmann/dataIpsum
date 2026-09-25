"""Validação do `docker-compose.yml` de dev (DD-02 §G.3.2, §G.6). Marcados
`docker`: exigem o CLI `docker compose config` (não `docker build`), então são
bem mais leves que os testes de imagem, mas ainda fora do job de testes
rápidos (`-m "not integration and not slow and not ray and not docker"`).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

REPO_ROOT = Path(__file__).resolve().parents[3]


def _compose_config(*, profile: str | None = None) -> dict[str, object]:
    cmd = ["docker", "compose"]
    if profile is not None:
        cmd += ["--profile", profile]
    cmd += ["config", "--format", "json"]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def test_docker_compose_config_e_valido() -> None:
    config = _compose_config()
    assert set(config["services"]) >= {"dataipsum", "ollama", "ollama-pull"}


def test_ollama_nao_publica_porta() -> None:
    config = _compose_config()
    assert "ports" not in config["services"]["ollama"]


def test_dataipsum_e_endurecido() -> None:
    service = _compose_config()["services"]["dataipsum"]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["user"] == "10001:10001"


def test_dataipsum_usa_o_dockerfile_gerado_da_raiz() -> None:
    service = _compose_config()["services"]["dataipsum"]
    assert service["build"]["dockerfile"] == "Dockerfile"
    assert service["build"]["context"] == str(REPO_ROOT)


def test_volume_de_modelos_fica_em_var_cache_dataipsum_models() -> None:
    service = _compose_config()["services"]["dataipsum"]
    targets = {volume["target"]: volume for volume in service["volumes"]}
    assert "/var/cache/dataipsum/models" in targets
    model_volume = targets["/var/cache/dataipsum/models"]
    assert model_volume["type"] == "volume"
    assert model_volume["source"] == "dataipsum-models"
    # rootfs read_only, mas o volume nomeado continua gravável (não tem read_only: true).
    assert not model_volume.get("read_only", False)


def test_profile_gpu_reserva_gpu_para_o_ollama() -> None:
    config = _compose_config(profile="gpu")
    assert "ollama-gpu" in config["services"]
    gpu_service = config["services"]["ollama-gpu"]
    assert gpu_service["profiles"] == ["gpu"]
    devices = gpu_service["deploy"]["resources"]["reservations"]["devices"]
    assert any("gpu" in device.get("capabilities", []) for device in devices)
