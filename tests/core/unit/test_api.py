"""Testes de `dataipsum.api` (DD-00 §7.1: api.py).

`load_schema`/`validate` delegam para `dataipsum.schema.loader`, mockado via
`unittest.mock.patch` nos pontos de costura `_load_schema`/`_validate` (ver o
docstring de `tests/core/unit/conftest.py`). `generate`/`resume`/`plan` são a
integração do motor (DD-01 §S5): os testes abaixo checam a delegação para
`dataipsum.relations.RelationsPlanner`/`dataipsum.execution.orchestrator`/
`dataipsum.execution.local_executor.LocalExecutor` via mocks, sem rodar uma
geração real (isso já é coberto por `tests/integration/motor/`).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from dataipsum import api
from dataipsum.config import RunOptions, SinkConfig
from dataipsum.errors import OutputDirError
from dataipsum.execution.orchestrator import OrchestratorResult


def _run_options(out_dir: Path) -> RunOptions:
    return RunOptions(out_dir=out_dir, sink=SinkConfig(kind="parquet"))


def _schema_stub(*, seed: int | None = 7, chunk_size: int = 1_000) -> SimpleNamespace:
    return SimpleNamespace(seed=seed, chunk_size=chunk_size)


# --- load_schema / validate: delegação ---------------------------------------


def test_load_schema_delega_ao_loader() -> None:
    sentinel_schema = object()
    with patch("dataipsum.api._load_schema", return_value=sentinel_schema) as mocked:
        result = api.load_schema("schema.yaml")
    mocked.assert_called_once_with("schema.yaml")
    assert result is sentinel_schema


def test_validate_delega_ao_loader() -> None:
    sentinel_report = object()
    sentinel_schema = object()
    with patch("dataipsum.api._validate", return_value=sentinel_report) as mocked:
        result = api.validate(sentinel_schema)
    mocked.assert_called_once_with(sentinel_schema)
    assert result is sentinel_report


# --- plan: delega para RelationsPlanner (DD-01 §S5) ---------------------------


def test_plan_delega_para_relations_planner_com_seed_e_chunk_size_das_options() -> None:
    schema = _schema_stub(seed=1)
    options = _run_options(Path("/tmp/out")).__class__(
        out_dir=Path("/tmp/out"), sink=SinkConfig(kind="fake"), seed=99, chunk_size=50
    )
    sentinel_plan = object()
    stub_planner = MagicMock()
    stub_planner.plan.return_value = sentinel_plan
    with patch("dataipsum.api.RelationsPlanner", return_value=stub_planner) as planner_cls:
        result = api.plan(schema, options)
    planner_cls.assert_called_once_with()
    stub_planner.plan.assert_called_once_with(schema, 99, 50)
    assert result is sentinel_plan


def test_plan_usa_seed_e_chunk_size_do_schema_quando_options_nao_definem() -> None:
    schema = _schema_stub(seed=42, chunk_size=123)
    options = _run_options(Path("/tmp/out"))
    stub_planner = MagicMock()
    with patch("dataipsum.api.RelationsPlanner", return_value=stub_planner):
        api.plan(schema, options)
    stub_planner.plan.assert_called_once_with(schema, 42, 123)


# --- export_schema / import_ddl: esqueletos (trilha F) ------------------------


def test_export_schema_levanta_notimplementederror_trilha_f(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError, match="trilha F"):
        api.export_schema(object(), "ddl", out_dir=tmp_path)


def test_import_ddl_levanta_notimplementederror_trilha_f() -> None:
    with pytest.raises(NotImplementedError, match="trilha F"):
        api.import_ddl("CREATE TABLE x (id INT);", "postgres")


# --- generate: guardrail de diretório de saída ---------------------------------


def test_generate_recusa_out_dir_nao_vazio_sem_manifesto(tmp_path: Path) -> None:
    (tmp_path / "arquivo_qualquer.txt").write_text("x", encoding="utf-8")
    options = _run_options(tmp_path)
    with pytest.raises(OutputDirError):
        api.generate(object(), options)
    assert list(tmp_path.iterdir()) == [tmp_path / "arquivo_qualquer.txt"]


def test_generate_recusa_out_dir_com_manifesto_anterior_e_sugere_resume(tmp_path: Path) -> None:
    (tmp_path / "_manifest.json").write_text("{}", encoding="utf-8")
    options = _run_options(tmp_path)
    with pytest.raises(OutputDirError, match=f"resume {tmp_path}"):
        api.generate(object(), options)
    assert (tmp_path / "_manifest.json").read_text(encoding="utf-8") == "{}"


# --- generate / resume: delegação para o orquestrador (DD-01 §S5) -------------


def _orchestrator_result(out_dir: Path) -> OrchestratorResult:
    return OrchestratorResult(
        run_id="r1",
        status="completed",
        manifest_path=out_dir / "_manifest.json",
        tables={"usuarios": 10},
        pending_chunks=0,
    )


def test_generate_delega_para_orchestrator_com_planner_e_executor_locais(tmp_path: Path) -> None:
    schema = _schema_stub()
    options = _run_options(tmp_path / "out")
    result = _orchestrator_result(options.out_dir)
    stub_executor = MagicMock()

    with (
        patch("dataipsum.api.LocalExecutor", return_value=stub_executor) as executor_cls,
        patch("dataipsum.api.RelationsPlanner") as planner_cls,
        patch("dataipsum.api.orchestrator.generate", return_value=result) as orchestrator_generate,
    ):
        run_result = api.generate(schema, options)

    executor_cls.assert_called_once()
    planner_cls.assert_called_once_with()
    orchestrator_generate.assert_called_once_with(
        schema, options, planner=planner_cls.return_value, executor=stub_executor
    )
    stub_executor.shutdown.assert_called_once_with(wait=True)
    assert run_result.run_id == "r1"
    assert run_result.status == "completed"
    assert run_result.tables == {"usuarios": 10}


def test_generate_desliga_o_executor_mesmo_com_erro_do_orquestrador(tmp_path: Path) -> None:
    schema = _schema_stub()
    options = _run_options(tmp_path / "out")
    stub_executor = MagicMock()

    with (
        patch("dataipsum.api.LocalExecutor", return_value=stub_executor),
        patch("dataipsum.api.RelationsPlanner"),
        patch("dataipsum.api.orchestrator.generate", side_effect=RuntimeError("boom")),
        pytest.raises(RuntimeError, match="boom"),
    ):
        api.generate(schema, options)

    stub_executor.shutdown.assert_called_once_with(wait=True)


def test_resume_delega_para_orchestrator_com_executor_local(tmp_path: Path) -> None:
    options = _run_options(tmp_path)
    result = _orchestrator_result(tmp_path)
    stub_executor = MagicMock()

    with (
        patch("dataipsum.api.LocalExecutor", return_value=stub_executor) as executor_cls,
        patch("dataipsum.api.orchestrator.resume", return_value=result) as orchestrator_resume,
    ):
        run_result = api.resume(tmp_path, options)

    executor_cls.assert_called_once()
    orchestrator_resume.assert_called_once_with(tmp_path, options, executor=stub_executor)
    stub_executor.shutdown.assert_called_once_with(wait=True)
    assert run_result.status == "completed"
    assert run_result.pending_chunks == 0
