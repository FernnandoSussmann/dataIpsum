"""Layout de arquivos e escrita atômica por chunk (DD-02, trilha E, E.3.1).

Compartilhado pelos sinks de arquivo (`csv`, `json`, `jsonl`, `parquet`). Os sinks de
banco e o sink Kafka não usam este módulo.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid as uuid_lib
from collections.abc import Callable
from pathlib import Path

from dataipsum.errors import SinkError
from dataipsum.manifest import confine_to_output_dir
from dataipsum.schema.models import IDENTIFIER_PATTERN

MIN_PART_ID_WIDTH = 5

TEMP_FILE_PATTERN = re.compile(r"^\.part-\d+\.[a-z]+\.tmp-[0-9a-f-]{36}$")

_FSYNC_READ_CHUNK_SIZE = 1024 * 1024


def validate_table_name(name: str) -> str:
    """Confinamento por nome (E.5.1): o nome do arquivo deriva só de identificadores
    validados e do ID numérico do chunk."""
    if not IDENTIFIER_PATTERN.fullmatch(name):
        raise SinkError(f"nome de tabela inválido para sink de arquivo: '{name}'")
    return name


def part_filename(chunk_id: int, extension: str) -> str:
    """`part-<id>.<ext>`, com zero-padding de 5 dígitos, ampliado se `chunk_id` exigir
    mais dígitos (E.3.1)."""
    if chunk_id < 1:
        raise SinkError(f"chunk_id deve ser >= 1, recebido {chunk_id}")
    width = max(MIN_PART_ID_WIDTH, len(str(chunk_id)))
    return f"part-{chunk_id:0{width}d}.{extension}"


def table_dir_for(out_dir: Path, table_name: str) -> Path:
    """`<out>/<tabela>/`, confinado a `<out>` e criado se necessário."""
    validate_table_name(table_name)
    candidate = out_dir / table_name
    candidate.mkdir(parents=True, exist_ok=True)
    return confine_to_output_dir(out_dir, candidate)


def cleanup_orphan_temp_files(table_dir: Path) -> None:
    """Remove só os temporários órfãos que casam com o padrão exato (E.3.1, E.5.2):
    `^\\.part-\\d+\\.[a-z]+\\.tmp-[0-9a-f-]{36}$`. Nenhum outro arquivo é tocado."""
    for entry in table_dir.iterdir():
        if entry.is_file() and TEMP_FILE_PATTERN.fullmatch(entry.name):
            entry.unlink(missing_ok=True)


def write_bytes_atomically(
    table_dir: Path, final_name: str, produce: Callable[[Path], None]
) -> str:
    """Escreve `final_name` atomicamente dentro de `table_dir` (E.3.1):

    1. `produce` grava o conteúdo em um caminho temporário no mesmo diretório;
    2. `fsync` do arquivo;
    3. `os.replace` para o nome final;
    4. `fsync` do diretório.

    Devolve o sha256 do conteúdo final. Se `produce` ou o replace falharem, o
    temporário é removido e o arquivo final (se já existia) não é tocado.
    """
    final_path = confine_to_output_dir(table_dir, table_dir / final_name)
    tmp_name = f".{final_name}.tmp-{uuid_lib.uuid4()}"
    tmp_path = confine_to_output_dir(table_dir, table_dir / tmp_name)
    try:
        produce(tmp_path)
        with tmp_path.open("rb") as tmp_file:
            os.fsync(tmp_file.fileno())
        digest = _sha256_of_file(tmp_path)
        os.replace(tmp_path, final_path)
        _fsync_directory(table_dir)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise SinkError(f"falha ao gravar '{final_path}' atomicamente: {exc}") from exc
    return digest


def _sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(_FSYNC_READ_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _fsync_directory(directory: Path) -> None:
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
