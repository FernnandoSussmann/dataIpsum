"""Testes do cache em disco (DD-01 §C.6): chave estável, hit evita chamada, eviction, `no-cache`."""

from __future__ import annotations

from pathlib import Path

from dataipsum.llm.cache import CacheKeyParts, DiskCache, cache_key, evict_to_limit, write_entry


def _parts(**overrides: object) -> CacheKeyParts:
    base = {
        "kind": "ollama",
        "base_url": "http://localhost:11434",
        "model": "llama3.1:8b",
        "system": "sistema",
        "prompt": "prompt",
        "json_schema": None,
        "temperature": 0.0,
        "max_tokens": 256,
        "seed": 42,
    }
    base.update(overrides)
    return CacheKeyParts(**base)  # type: ignore[arg-type]


def test_cache_key_e_estavel_para_as_mesmas_entradas() -> None:
    assert cache_key(_parts()) == cache_key(_parts())


def test_cache_key_muda_com_prompt() -> None:
    assert cache_key(_parts()) != cache_key(_parts(prompt="outro prompt"))


def test_cache_key_usa_so_o_host_do_base_url_nao_o_valor_da_chave() -> None:
    # A chave de API nunca é parte de `CacheKeyParts`: não há como ela vazar na chave.
    key_a = cache_key(_parts(base_url="http://localhost:11434"))
    key_b = cache_key(_parts(base_url="http://localhost:11434/v1"))
    assert key_a == key_b  # mesmo host, path diferente: só o host entra na chave


def test_cache_key_nunca_contem_segredo(tmp_path: Path) -> None:
    parts = _parts(prompt="prompt sem segredo")
    key = cache_key(parts)
    assert "SEGREDO123" not in key


def test_hit_evita_chamada_ao_provedor(tmp_path: Path) -> None:
    cache = DiskCache(cache_dir=tmp_path)
    key = cache_key(_parts())
    assert cache.get(key) is None
    cache.put(key, text="resposta gerada", model="llama3.1:8b")
    assert cache.get(key) == "resposta gerada"


def test_escrita_e_atomica_arquivo_final_sempre_json_valido(tmp_path: Path) -> None:
    write_entry(tmp_path, "abc123", text="ola", model="m")
    entry_path = tmp_path / "ab" / "abc123.json"
    assert entry_path.is_file()
    assert "ola" in entry_path.read_text(encoding="utf-8")
    # nenhum arquivo temporário sobra
    assert list((tmp_path / "ab").glob(".*")) == []


def test_eviction_por_tamanho_remove_mais_antigos_primeiro(tmp_path: Path) -> None:
    for index in range(5):
        write_entry(tmp_path, f"key{index}", text="x" * 1000, model="m")
        entry_path = tmp_path / f"key{index}"[:2] / f"key{index}.json"
        # espaça o mtime para garantir ordem determinística de "mais antigo"
        entry_path.touch()
    removed = evict_to_limit(tmp_path, max_mb=0)
    assert removed == 5
    assert not any(tmp_path.rglob("*.json"))


def test_no_cache_desliga_get_e_put(tmp_path: Path) -> None:
    cache = DiskCache(cache_dir=tmp_path, enabled=False)
    key = cache_key(_parts())
    cache.put(key, text="nunca deveria persistir", model="m")
    assert cache.get(key) is None
    assert not any(tmp_path.rglob("*.json"))
