"""Manifesto da execução: leitura/escrita atômica, confinamento de caminho e
sanitização de segredos (DD-00 §3.7, §6.4, §6.5).

O manifesto é escrito **só pelo processo driver** (§3.7); este módulo não
assume concorrência entre escritores.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from dataipsum.contracts.executor import BlockedBy, ChunkResultFlags, ChunkStatus
from dataipsum.errors import ManifestError, ManifestMismatchError, OutputDirError

MANIFEST_FILENAME = "_manifest.json"
CURRENT_MANIFEST_VERSION = 1

ManifestStatus = Literal["running", "completed", "partial", "failed"]
SeedSource = Literal["user", "random"]
EmittedSchemaFormat = Literal["ddl", "avro"]

_SECRET_KEY_PATTERN = re.compile(r"(?i)pass|secret|token|key")
_ENV_SUFFIX = "_env"


def sanitize_sink_options(options: dict[str, object]) -> dict[str, object]:
    """Remove chaves de segredo (§6.5), preservando as terminadas em `_env`.

    Uma chave `*_env` guarda só o **nome** de uma variável de ambiente, nunca
    o valor do segredo, então é segura para ir ao manifesto e aos logs.
    """
    return {
        key: value
        for key, value in options.items()
        if key.lower().endswith(_ENV_SUFFIX) or not _SECRET_KEY_PATTERN.search(key)
    }


def compute_schema_sha256(schema: dict[str, object]) -> str:
    """Hash determinístico do schema normalizado, para `schema_sha256` (§3.7)."""
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def raise_if_schema_mismatch(manifest_schema_sha256: str, provided_schema_sha256: str) -> None:
    """`resume` com um schema cujo hash difere do embutido no manifesto (§3.7)."""
    if manifest_schema_sha256 != provided_schema_sha256:
        raise ManifestMismatchError(
            "o schema informado não corresponde ao schema gravado no manifesto "
            f"(esperado sha256={manifest_schema_sha256}, recebido sha256={provided_schema_sha256})"
        )


def _major_version(version: str) -> str:
    return version.split(".", 1)[0]


def raise_if_major_version_mismatch(
    manifest_dataipsum_version: str, current_dataipsum_version: str
) -> None:
    """`resume` com uma versão major do dataipsum incompatível com o manifesto (§3.7)."""
    if _major_version(manifest_dataipsum_version) != _major_version(current_dataipsum_version):
        raise ManifestMismatchError(
            "versão major do dataipsum incompatível com o manifesto "
            f"(manifesto={manifest_dataipsum_version}, execução atual={current_dataipsum_version})"
        )


def confine_to_output_dir(out_dir: Path, candidate: Path) -> Path:
    """Garante que `candidate` resolve para dentro de `out_dir` (§6.4).

    Cobre travessia por `../` e symlinks (dentro ou fora de `<out>`): a
    resolução segue links simbólicos, e um `candidate` que seja ele mesmo um
    symlink é recusado mesmo que aponte para dentro de `out_dir`.
    """
    resolved_out_dir = out_dir.resolve()
    if candidate.is_symlink():
        raise OutputDirError(
            f"symlinks não são permitidos dentro do diretório de saída: '{candidate}'"
        )
    resolved_candidate = candidate.resolve()
    is_inside = (
        resolved_candidate == resolved_out_dir or resolved_out_dir in resolved_candidate.parents
    )
    if not is_inside:
        raise OutputDirError(f"caminho '{candidate}' está fora do diretório de saída '{out_dir}'")
    return resolved_candidate


def check_output_dir_for_generate(out_dir: Path) -> None:
    """`generate` exige `<out>` inexistente ou vazio (§6.4, critério 19).

    Qualquer `<out>` não vazio é recusado, **inclusive** se contiver só um
    `_manifest.json` de uma execução anterior — nesse caso a mensagem sugere
    `dataipsum resume <out>`.
    """
    if not out_dir.exists():
        return
    if any(out_dir.iterdir()):
        raise OutputDirError(
            f"'{out_dir}' já existe e não está vazio. Use 'dataipsum resume {out_dir}' "
            "para retomar essa execução, ou escolha outro diretório para gerar de novo."
        )


@dataclass(frozen=True)
class ManifestFlushPolicy:
    """Decide quando gravar o manifesto: a cada N chunks, a cada S segundos ou
    no fim (§3.7). Recebe o número de chunks e os segundos já decorridos
    desde o último flush, calculados pelo chamador a partir de um relógio
    injetável (ex.: `time.monotonic`) — os testes não precisam dormir, só
    fabricar esses dois números.
    """

    chunk_batch_size: int = 50
    interval_seconds: float = 5.0

    def should_flush(
        self,
        chunks_done_since_last_flush: int,
        seconds_since_last_flush: float,
        *,
        is_final: bool = False,
    ) -> bool:
        return (
            is_final
            or chunks_done_since_last_flush >= self.chunk_batch_size
            or seconds_since_last_flush >= self.interval_seconds
        )


@dataclass(frozen=True)
class ManifestChunkEntry:
    """Entrada de `manifest.chunks[<tabela>][<chunk_id>]` (§3.7)."""

    status: ChunkStatus
    rows: int
    attempts: int
    sink_ref: str | None = None
    sha256: str | None = None
    flags: ChunkResultFlags = field(default_factory=ChunkResultFlags)
    blocked_by: tuple[BlockedBy, ...] = ()
    error: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "rows": self.rows,
            "attempts": self.attempts,
            "sink_ref": self.sink_ref,
            "sha256": self.sha256,
            "flags": asdict(self.flags),
            "blocked_by": [asdict(blocked) for blocked in self.blocked_by],
            "error": self.error,
        }

    @staticmethod
    def from_json_dict(data: dict[str, Any]) -> ManifestChunkEntry:
        return ManifestChunkEntry(
            status=cast(ChunkStatus, data["status"]),
            rows=data["rows"],
            attempts=data["attempts"],
            sink_ref=data.get("sink_ref"),
            sha256=data.get("sha256"),
            flags=ChunkResultFlags(**data.get("flags", {})),
            blocked_by=tuple(BlockedBy(**blocked) for blocked in data.get("blocked_by", [])),
            error=data.get("error"),
        )


@dataclass(frozen=True)
class LLMProviderUsed:
    name: str
    kind: str
    model: str


@dataclass(frozen=True)
class EmittedSchema:
    format: EmittedSchemaFormat
    path: str
    sha256: str
    dialect: str | None = None
    table: str | None = None


@dataclass(frozen=True)
class Manifest:
    """Conteúdo de `<out>/_manifest.json` (DD-00 §3.7)."""

    run_id: str
    dataipsum_version: str
    created_at: str
    updated_at: str
    status: ManifestStatus
    seed: int
    seed_source: SeedSource
    chunk_size: int
    schema: dict[str, object]
    schema_sha256: str
    sink: dict[str, object]
    plan: dict[str, object]
    chunks: dict[str, dict[str, ManifestChunkEntry]] = field(default_factory=dict)
    providers_used: tuple[LLMProviderUsed, ...] = ()
    emitted_schemas: tuple[EmittedSchema, ...] = ()
    manifest_version: int = CURRENT_MANIFEST_VERSION

    def to_json_dict(self) -> dict[str, object]:
        sink_options = cast(dict[str, object], self.sink.get("options", {}))
        return {
            "manifest_version": self.manifest_version,
            "run_id": self.run_id,
            "dataipsum_version": self.dataipsum_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "seed": self.seed,
            "seed_source": self.seed_source,
            "chunk_size": self.chunk_size,
            "schema": self.schema,
            "schema_sha256": self.schema_sha256,
            "sink": {"kind": self.sink.get("kind"), "options": sanitize_sink_options(sink_options)},
            "plan": self.plan,
            "chunks": {
                table: {chunk_id: entry.to_json_dict() for chunk_id, entry in table_chunks.items()}
                for table, table_chunks in self.chunks.items()
            },
            "llm": {"providers_used": [asdict(provider) for provider in self.providers_used]},
            "emitted_schemas": [asdict(emitted) for emitted in self.emitted_schemas],
        }

    @staticmethod
    def from_json_dict(data: dict[str, Any]) -> Manifest:
        chunks_data = cast(dict[str, dict[str, dict[str, Any]]], data.get("chunks", {}))
        return Manifest(
            run_id=data["run_id"],
            dataipsum_version=data["dataipsum_version"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            status=cast(ManifestStatus, data["status"]),
            seed=data["seed"],
            seed_source=cast(SeedSource, data["seed_source"]),
            chunk_size=data["chunk_size"],
            schema=cast(dict[str, object], data["schema"]),
            schema_sha256=data["schema_sha256"],
            sink=cast(dict[str, object], data["sink"]),
            plan=cast(dict[str, object], data["plan"]),
            chunks={
                table: {
                    chunk_id: ManifestChunkEntry.from_json_dict(entry)
                    for chunk_id, entry in table_chunks.items()
                }
                for table, table_chunks in chunks_data.items()
            },
            providers_used=tuple(
                LLMProviderUsed(**provider)
                for provider in data.get("llm", {}).get("providers_used", [])
            ),
            emitted_schemas=tuple(
                EmittedSchema(**emitted) for emitted in data.get("emitted_schemas", [])
            ),
            manifest_version=data.get("manifest_version", CURRENT_MANIFEST_VERSION),
        )


def write_manifest_atomic(out_dir: Path, manifest: Manifest) -> None:
    """Grava `<out>/_manifest.json` atomicamente (§3.7).

    Escreve em `<out>/._manifest.json.tmp-<uuid>`, faz `fsync` do arquivo,
    `os.replace` para o nome final e `fsync` do diretório. Se o processo for
    interrompido antes do `os.replace`, o `_manifest.json` anterior (se
    houver) permanece intacto e válido.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / MANIFEST_FILENAME
    tmp_path = confine_to_output_dir(out_dir, out_dir / f"._manifest.json.tmp-{uuid.uuid4().hex}")
    payload = json.dumps(manifest.to_json_dict(), indent=2, sort_keys=True, ensure_ascii=False)
    try:
        with tmp_path.open("w", encoding="utf-8") as tmp_file:
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, final_path)
        dir_fd = os.open(out_dir, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise ManifestError(
            f"falha ao gravar '{final_path}' atomicamente: {exc}. "
            f"O manifesto anterior (se houver) não foi alterado."
        ) from exc


def read_manifest(out_dir: Path) -> Manifest:
    """Lê e desserializa `<out>/_manifest.json`."""
    path = out_dir / MANIFEST_FILENAME
    return Manifest.from_json_dict(json.loads(path.read_text(encoding="utf-8")))
