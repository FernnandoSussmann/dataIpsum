"""Teste de arquitetura (DD-00 §3.6, "Proibido nas trilhas"; §8, critério 11).

`seeds.py` é a única fonte de aleatoriedade autorizada em `dataipsum`. Nenhum
outro arquivo do pacote pode usar `random`, `numpy.random` global ou
`Faker.seed()`.
"""

from __future__ import annotations

from pathlib import Path

import dataipsum

_FORBIDDEN_SUBSTRINGS = ("import random", "from random", "np.random.")

_ALLOWED_FILE = "seeds.py"


def _source_files() -> list[Path]:
    package_root = Path(dataipsum.__file__).parent
    return sorted(package_root.rglob("*.py"))


def test_nenhum_arquivo_fora_de_seeds_usa_aleatoriedade_global() -> None:
    ofensores: dict[str, list[str]] = {}
    for path in _source_files():
        if path.name == _ALLOWED_FILE:
            continue
        source = path.read_text(encoding="utf-8")
        achados = [substring for substring in _FORBIDDEN_SUBSTRINGS if substring in source]
        if achados:
            ofensores[str(path)] = achados

    assert not ofensores, f"aleatoriedade fora de {_ALLOWED_FILE}: {ofensores}"


def test_seeds_py_e_o_unico_arquivo_isento_e_existe() -> None:
    arquivos = {path.name for path in _source_files()}
    assert _ALLOWED_FILE in arquivos


def test_deteccao_funciona_em_uma_fixture_com_random(tmp_path: Path) -> None:
    arquivo_com_ofensa = tmp_path / "modulo_qualquer.py"
    arquivo_com_ofensa.write_text("import random\n\nrandom.seed(1)\n", encoding="utf-8")

    source = arquivo_com_ofensa.read_text(encoding="utf-8")
    achados = [substring for substring in _FORBIDDEN_SUBSTRINGS if substring in source]

    assert achados == ["import random"]
