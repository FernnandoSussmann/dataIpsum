"""Testes de `dataipsum.manifest` (DD-00 §7.1: manifest.py)."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from dataipsum.contracts.executor import BlockedBy, ChunkResultFlags
from dataipsum.errors import ManifestError, ManifestMismatchError, OutputDirError
from dataipsum.manifest import (
    Manifest,
    ManifestChunkEntry,
    ManifestFlushPolicy,
    check_output_dir_for_generate,
    compute_schema_sha256,
    confine_to_output_dir,
    raise_if_major_version_mismatch,
    raise_if_schema_mismatch,
    read_manifest,
    sanitize_sink_options,
    write_manifest_atomic,
)


def _build_manifest(**overrides: object) -> Manifest:
    schema = {"version": 1, "name": "loja", "tables": []}
    base = Manifest(
        run_id="11111111-1111-1111-1111-111111111111",
        dataipsum_version="0.1.0",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:05Z",
        status="running",
        seed=42,
        seed_source="user",
        chunk_size=10_000,
        schema=schema,
        schema_sha256=compute_schema_sha256(schema),
        sink={"kind": "postgres", "options": {"password_env": "PG_PASS", "dsn": "x"}},
        plan={"order": ["usuarios"], "tables": {}},
        chunks={
            "usuarios": {
                "0": ManifestChunkEntry(
                    status="done",
                    rows=10_000,
                    attempts=1,
                    sink_ref="postgres://usuarios/0",
                    sha256="abc123",
                    flags=ChunkResultFlags(placeholders=1),
                    blocked_by=(BlockedBy(table="produtos", chunk_id=0),),
                ),
            },
        },
    )
    return replace(base, **overrides) if overrides else base


# --- round-trip -------------------------------------------------------------


def test_manifest_round_trip(tmp_path: Path) -> None:
    manifest = _build_manifest()
    write_manifest_atomic(tmp_path, manifest)
    restored = read_manifest(tmp_path)
    assert restored == manifest


def test_manifest_to_json_dict_tem_o_formato_do_3_7() -> None:
    manifest = _build_manifest()
    as_dict = manifest.to_json_dict()
    assert as_dict["manifest_version"] == 1
    assert as_dict["status"] == "running"
    assert as_dict["chunks"]["usuarios"]["0"]["status"] == "done"
    assert as_dict["chunks"]["usuarios"]["0"]["blocked_by"] == [
        {"table": "produtos", "chunk_id": 0}
    ]
    assert as_dict["llm"] == {"providers_used": []}
    assert as_dict["emitted_schemas"] == []


# --- escrita atômica (criterio 12; cenário "Manifesto atômico") -------------


def test_write_manifest_atomic_grava_e_pode_ser_relido(tmp_path: Path) -> None:
    write_manifest_atomic(tmp_path, _build_manifest())
    final_path = tmp_path / "_manifest.json"
    assert final_path.exists()
    assert not list(tmp_path.glob("._manifest.json.tmp-*"))
    json.loads(final_path.read_text(encoding="utf-8"))  # é JSON válido


def test_write_manifest_atomic_sobrevive_a_falha_antes_do_replace(tmp_path: Path) -> None:
    manifest_anterior = _build_manifest(status="running")
    write_manifest_atomic(tmp_path, manifest_anterior)
    final_path = tmp_path / "_manifest.json"
    conteudo_anterior = final_path.read_text(encoding="utf-8")

    manifest_novo = _build_manifest(status="completed")
    with (
        patch("dataipsum.manifest.os.replace", side_effect=OSError("kill -9 simulado")),
        pytest.raises(ManifestError),
    ):
        write_manifest_atomic(tmp_path, manifest_novo)

    assert final_path.read_text(encoding="utf-8") == conteudo_anterior
    json.loads(final_path.read_text(encoding="utf-8"))  # continua JSON válido
    restored = read_manifest(tmp_path)
    assert restored.status == "running"


# --- flush em lote -----------------------------------------------------------


def test_flush_policy_a_cada_50_chunks() -> None:
    policy = ManifestFlushPolicy(chunk_batch_size=50, interval_seconds=5.0)
    assert policy.should_flush(49, 0.0) is False
    assert policy.should_flush(50, 0.0) is True


def test_flush_policy_a_cada_5_segundos_com_relogio_falso() -> None:
    policy = ManifestFlushPolicy(chunk_batch_size=50, interval_seconds=5.0)
    fake_clock = iter([0.0, 4.9, 5.0])
    started_at = next(fake_clock)

    def elapsed(now: float) -> float:
        return now - started_at

    assert policy.should_flush(1, elapsed(next(fake_clock))) is False
    assert policy.should_flush(1, elapsed(next(fake_clock))) is True


def test_flush_policy_no_fim_mesmo_sem_atingir_lote_ou_tempo() -> None:
    policy = ManifestFlushPolicy()
    assert policy.should_flush(1, 0.1, is_final=True) is True


# --- confinamento de caminho (guardrail §6.4; criterio 15) -------------------


def test_confine_to_output_dir_aceita_caminho_dentro(tmp_path: Path) -> None:
    candidate = tmp_path / "arquivo.txt"
    resolved = confine_to_output_dir(tmp_path, candidate)
    assert resolved == candidate.resolve()


def test_confine_to_output_dir_recusa_travessia_com_dotdot(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    candidate = out_dir / ".." / "fora.txt"
    with pytest.raises(OutputDirError):
        confine_to_output_dir(out_dir, candidate)


def test_confine_to_output_dir_recusa_symlink_para_fora(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    link = out_dir / "link"
    link.symlink_to(fora, target_is_directory=True)
    with pytest.raises(OutputDirError):
        confine_to_output_dir(out_dir, link)


def test_confine_to_output_dir_recusa_symlink_mesmo_apontando_para_dentro(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    real_file = out_dir / "real.txt"
    real_file.write_text("x")
    link = out_dir / "link.txt"
    link.symlink_to(real_file)
    with pytest.raises(OutputDirError):
        confine_to_output_dir(out_dir, link)


# --- diretório de saída para generate (criterio 19; cenário "Diretório com execução anterior") --


def test_check_output_dir_for_generate_aceita_inexistente(tmp_path: Path) -> None:
    check_output_dir_for_generate(tmp_path / "novo")


def test_check_output_dir_for_generate_aceita_vazio(tmp_path: Path) -> None:
    check_output_dir_for_generate(tmp_path)


def test_check_output_dir_for_generate_recusa_com_manifesto_previo(tmp_path: Path) -> None:
    (tmp_path / "_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(OutputDirError, match=f"resume {tmp_path}"):
        check_output_dir_for_generate(tmp_path)


def test_check_output_dir_for_generate_recusa_mesmo_sem_manifesto(tmp_path: Path) -> None:
    (tmp_path / "qualquer_arquivo.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OutputDirError):
        check_output_dir_for_generate(tmp_path)


# --- sanitizador de segredos (guardrail §6.5; criterio 13/20) ----------------


def test_sanitize_sink_options_remove_chaves_de_segredo() -> None:
    sanitized = sanitize_sink_options(
        {
            "password": "SEGREDO123",
            "secret": "x",
            "token": "y",
            "api_key": "z",
            "host": "db.local",
        }
    )
    assert sanitized == {"host": "db.local"}


def test_sanitize_sink_options_preserva_chaves_terminadas_em_env() -> None:
    options = {
        "password_env": "PG_PASS",
        "dsn_env": "DSN_VAR",
        "sasl_password_env": "SASL_VAR",
        "api_key_env": "ANTHROPIC_API_KEY",
    }
    assert sanitize_sink_options(options) == options


def test_manifesto_preserva_nome_da_variavel_mas_nunca_o_valor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PG_PASS", "SEGREDO123")
    manifest = _build_manifest(
        sink={"kind": "postgres", "options": {"password_env": "PG_PASS", "dsn": "db.local"}}
    )
    write_manifest_atomic(tmp_path, manifest)
    raw_text = (tmp_path / "_manifest.json").read_text(encoding="utf-8")
    assert '"password_env": "PG_PASS"' in raw_text
    assert "SEGREDO123" not in raw_text
    assert os.environ["PG_PASS"] == "SEGREDO123"


# --- ManifestMismatchError (regras de retomada §3.7) -------------------------


def test_raise_if_schema_mismatch_com_hashes_iguais_nao_levanta() -> None:
    raise_if_schema_mismatch("abc", "abc")


def test_raise_if_schema_mismatch_com_hashes_diferentes_levanta() -> None:
    with pytest.raises(ManifestMismatchError):
        raise_if_schema_mismatch("abc", "def")


def test_raise_if_major_version_mismatch_mesma_major_nao_levanta() -> None:
    raise_if_major_version_mismatch("1.2.0", "1.9.3")


def test_raise_if_major_version_mismatch_major_diferente_levanta() -> None:
    with pytest.raises(ManifestMismatchError):
        raise_if_major_version_mismatch("1.2.0", "2.0.0")


def test_compute_schema_sha256_e_deterministico() -> None:
    schema = {"version": 1, "tables": [{"name": "usuarios"}]}
    assert compute_schema_sha256(schema) == compute_schema_sha256(dict(schema))
