"""Cache em disco de respostas LLM (DD-01 §C.3.6). Chave nunca inclui a chave de API."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class CacheKeyParts:
    kind: str
    base_url: str | None
    model: str
    system: str
    prompt: str
    json_schema: dict[str, object] | None
    temperature: float
    max_tokens: int
    seed: int | None


def _host_of(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    return urlsplit(base_url).hostname


def cache_key(parts: CacheKeyParts) -> str:
    """`sha256` de um JSON canônico (chaves ordenadas). Nunca inclui credenciais (§C.3.6)."""
    canonical = {
        "kind": parts.kind,
        "host": _host_of(parts.base_url),
        "model": parts.model,
        "system": parts.system,
        "prompt": parts.prompt,
        "json_schema": parts.json_schema,
        "temperature": parts.temperature,
        "max_tokens": parts.max_tokens,
        "seed": parts.seed,
    }
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheEntry:
    text: str
    created_at: str
    model: str


def _entry_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / key[:2] / f"{key}.json"


def read_entry(cache_dir: Path, key: str) -> CacheEntry | None:
    path = _entry_path(cache_dir, key)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or "text" not in payload:
        return None
    return CacheEntry(
        text=str(payload["text"]),
        created_at=str(payload.get("created_at", "")),
        model=str(payload.get("model", "")),
    )


def write_entry(cache_dir: Path, key: str, *, text: str, model: str) -> None:
    """Escrita atômica: grava num arquivo temporário no mesmo diretório e faz `rename`."""
    path = _entry_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "text": text,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
    }
    tmp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, path)


def _cache_files(cache_dir: Path) -> list[Path]:
    if not cache_dir.is_dir():
        return []
    return [path for path in cache_dir.rglob("*.json") if path.is_file()]


def current_size_mb(cache_dir: Path) -> float:
    return sum(path.stat().st_size for path in _cache_files(cache_dir)) / (1024 * 1024)


def evict_to_limit(cache_dir: Path, *, max_mb: int) -> int:
    """Remove os arquivos mais antigos por `mtime` até ficar sob `max_mb`.

    Devolve quantos arquivos foram removidos.
    """
    files = sorted(_cache_files(cache_dir), key=lambda path: path.stat().st_mtime)
    total_bytes = sum(path.stat().st_size for path in files)
    limit_bytes = max_mb * 1024 * 1024
    removed = 0
    index = 0
    while total_bytes > limit_bytes and index < len(files):
        path = files[index]
        total_bytes -= path.stat().st_size
        path.unlink(missing_ok=True)
        removed += 1
        index += 1
    return removed


@dataclass
class DiskCache:
    """Fachada usada pelos provedores/filler: `get`/`put` já fazem a eviction por tamanho."""

    cache_dir: Path
    max_mb: int = 2048
    enabled: bool = True

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        entry = read_entry(self.cache_dir, key)
        return None if entry is None else entry.text

    def put(self, key: str, *, text: str, model: str) -> None:
        if not self.enabled:
            return
        write_entry(self.cache_dir, key, text=text, model=model)
        evict_to_limit(self.cache_dir, max_mb=self.max_mb)
