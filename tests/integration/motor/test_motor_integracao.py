"""Integração ponta a ponta do motor (DD-01 §3, S5): critérios I-01 a I-06.

Schema de referência em `schema_referencia.yaml` (usuários, produtos com `llm_post`, pedidos
1:N, pedido_produto N:N via ponte, mensagens thread) com seed fixa (2026). Roda em
`LocalExecutor` (trilha D) com `FakeLLM`/`FakeToxicity` (DD-00 §3.11) no lugar dos provedores
reais — `dataipsum.testing.fakes.FakeSink` não é usado diretamente porque ele guarda os batches
só em memória, perdidos entre os processos `spawn` do `LocalExecutor` (§D.3.3); em vez disso,
`_support.HashingFileSink` (mesmo espírito de fake, mas grava em arquivo) deixa os dados
legíveis de volta pelo teste, para checar integridade referencial (I-03) e o hash (I-02). Não
depende do DD-02: nenhum sink real é registrado.

**Atualizar o golden (I-02):** se uma mudança intencional no motor alterar a saída determinística
do schema de referência, apague `golden_hash.json`, rode
`uv run pytest tests/integration/motor/test_motor_integracao.py -k golden -q` uma vez (o teste
escreve o arquivo quando ele não existe) e commit o novo arquivo com a justificativa no PR.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from _support import SINK_KIND, GoldenRunChunk, read_table

from dataipsum.config import RunOptions, SinkConfig
from dataipsum.execution import orchestrator
from dataipsum.execution.local_executor import LocalExecutor
from dataipsum.manifest import read_manifest
from dataipsum.relations import RelationsPlanner
from dataipsum.schema.loader import load_schema

_SCHEMA_PATH = Path(__file__).parent / "schema_referencia.yaml"
_GOLDEN_PATH = Path(__file__).parent / "golden_hash.json"

# Grande o bastante para nunca esgotar dentro de um único chunk (motor reconstrói o `FakeLLM` a
# cada chunk, DD-01 §D.3.3): o pior caso é uma thread com fallback mensagem a mensagem (§C.3.8),
# que consome 2 chamadas de tentativa estruturada + 1 por mensagem, por thread do chunk.
_HAPPY_RESPONSES = tuple(f"texto determinístico {i}" for i in range(4_000))

_REFERENTIAL_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("pedidos", "usuario_id", "usuarios"),
    ("pedido_produto", "pedido_id", "pedidos"),
    ("pedido_produto", "produto_id", "produtos"),
    ("mensagens", "pedido_id", "pedidos"),
    ("mensagens", "autor", "usuarios"),
)


def _schema() -> Any:
    return load_schema(_SCHEMA_PATH)


def _options(out_dir: Path) -> RunOptions:
    # `seed` explícita (não vem de `resolve_run_options`/schema aqui: o teste chama
    # `orchestrator.generate` direto, e `orchestrator.generate` só olha `options.seed` — sem
    # isso, cada run sortearia uma seed nova via `seeds.random_seed()` e o "golden" nunca bateria).
    return RunOptions(
        out_dir=out_dir,
        sink=SinkConfig(kind=SINK_KIND, options={"out_dir": str(out_dir)}),
        seed=2026,
    )


def _generate(out_dir: Path, *, llm_response_texts: tuple[str, ...]) -> Any:
    executor = LocalExecutor(run_chunk=GoldenRunChunk(llm_response_texts=llm_response_texts))
    try:
        return orchestrator.generate(
            _schema(), _options(out_dir), planner=RelationsPlanner(), executor=executor
        )
    finally:
        executor.shutdown(wait=True)


def _resume(out_dir: Path, *, llm_response_texts: tuple[str, ...]) -> Any:
    executor = LocalExecutor(run_chunk=GoldenRunChunk(llm_response_texts=llm_response_texts))
    try:
        return orchestrator.resume(out_dir, _options(out_dir), executor=executor)
    finally:
        executor.shutdown(wait=True)


# --- I-01: roda em LocalExecutor e gera o número planejado de linhas por tabela -----


def test_i01_gera_o_numero_planejado_de_linhas_por_tabela(tmp_path: Path) -> None:
    result = _generate(tmp_path / "out", llm_response_texts=_HAPPY_RESPONSES)

    assert result.status == "completed"
    for table, planned_rows in result.tables.items():
        actual_rows = read_table(tmp_path / "out", table).num_rows
        assert actual_rows == planned_rows, (
            f"{table}: esperado {planned_rows}, gravado {actual_rows}"
        )


# --- I-02: sha256 dos batches bate com o golden versionado --------------------------


def _canonical_chunk_hashes(out_dir: Path) -> dict[str, dict[str, str]]:
    manifest = read_manifest(out_dir)
    return {
        table: {chunk_id: entry.sha256 or "" for chunk_id, entry in sorted(chunks.items())}
        for table, chunks in sorted(manifest.chunks.items())
    }


def test_i02_hash_dos_batches_bate_com_o_golden_versionado(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    _generate(out_dir, llm_response_texts=_HAPPY_RESPONSES)
    chunk_hashes = _canonical_chunk_hashes(out_dir)
    canonical = json.dumps(chunk_hashes, sort_keys=True).encode("utf-8")
    combined = hashlib.sha256(canonical).hexdigest()

    if not _GOLDEN_PATH.exists():
        _GOLDEN_PATH.write_text(
            json.dumps(
                {"combined_sha256": combined, "chunks": chunk_hashes}, indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        pytest.fail(
            f"golden inexistente; criado agora em {_GOLDEN_PATH} — rode de novo para validar, "
            "e faça o commit do arquivo"
        )

    golden = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    assert combined == golden["combined_sha256"], (
        "hash do schema de referência mudou; se a mudança é intencional, apague "
        f"{_GOLDEN_PATH} e rode este teste de novo para recriá-lo (com justificativa no PR)"
    )
    assert chunk_hashes == golden["chunks"]


# --- I-03: integridade referencial: 100% das FKs resolvem ---------------------------


def test_i03_todas_as_fks_resolvem(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    _generate(out_dir, llm_response_texts=_HAPPY_RESPONSES)

    tables = {
        name: read_table(out_dir, name)
        for name in {"usuarios", "produtos", "pedidos", "pedido_produto", "mensagens"}
    }
    for child, fk_column, parent in _REFERENTIAL_CHECKS:
        fk_values = set(tables[child].column(fk_column).to_pylist())
        parent_pk_values = set(tables[parent].column("id").to_pylist())
        missing = fk_values - parent_pk_values
        assert not missing, (
            f"{child}.{fk_column} referencia PKs inexistentes em {parent}: {missing}"
        )


# --- I-04: resume depois de falha simulada do FakeLLM termina em completed ----------


def test_i04_resume_depois_de_falha_simulada_do_fakellm_termina_completed(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"

    first = _generate(out_dir, llm_response_texts=())  # FakeLLM sem respostas: falha imediata
    assert first.status == "partial"
    manifest = read_manifest(out_dir)
    pending_tables = {
        table
        for table, chunks in manifest.chunks.items()
        if any(entry.status == "pending_llm" for entry in chunks.values())
    }
    assert pending_tables, "o cenário deveria deixar ao menos uma tabela LLM pendente"

    second = _resume(out_dir, llm_response_texts=_HAPPY_RESPONSES)
    assert second.status == "completed"
    final_manifest = read_manifest(out_dir)
    assert all(
        entry.status == "done"
        for chunks in final_manifest.chunks.values()
        for entry in chunks.values()
    )


# --- I-05: teste de arquitetura do DD-00 (sem `random`) passa com todas as trilhas --


def test_i05_teste_de_arquitetura_sem_random_passa() -> None:
    """Mesma checagem de `tests/core/unit/test_architecture_no_random.py` (DD-00 §3.6),
    reimplementada aqui (em vez de importada — os módulos de `tests/` não formam um pacote,
    §S5 não muda isso) para confirmar explicitamente que ela passa com o código de A-D juntos."""
    import dataipsum

    forbidden = ("import random", "from random", "np.random.")
    package_root = Path(dataipsum.__file__).parent
    offenders = {
        str(path): hits
        for path in sorted(package_root.rglob("*.py"))
        if path.name != "seeds.py"
        for hits in [[s for s in forbidden if s in path.read_text(encoding="utf-8")]]
        if hits
    }
    assert not offenders, f"aleatoriedade fora de seeds.py: {offenders}"


# --- I-06: imagem Docker (só o teste marcado; não roda build aqui) ------------------


@pytest.mark.docker
@pytest.mark.integration
def test_i06_imagem_docker_gera_o_schema_de_referencia_com_o_mesmo_golden() -> None:
    pytest.skip(
        "I-06 exige build da imagem Docker com os fragmentos de A-D e rede desligada "
        "(--network none); fora do escopo de execução deste ambiente de teste (DD-01 §D.10, "
        "§S5). Ver tests/docker/test_image_*.py para o padrão usado pelas outras trilhas."
    )
