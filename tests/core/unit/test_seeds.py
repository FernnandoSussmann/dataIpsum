"""Testes de seeds.py (DD-00 §7.1: seeds.py; §8 critérios 8, 9, 10)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from numpy.typing import NDArray

from dataipsum.seeds import (
    FIRST_FREE_SLOT,
    FIRST_REJECTION_SLOT,
    INVALID_SLOT,
    LAST_FREE_SLOT,
    NULL_SLOT,
    Draws,
    choice,
    derive,
    draw_u64,
    integers,
    mix,
    normal,
    random_seed,
    seed_chunk,
    seed_column,
    seed_llm,
    seed_relation,
    seed_table,
    uniform,
)

ROOT_SEED = 42


# --- golden values (DD-00 §8, critério 8): fixados rodando a própria
# implementação uma vez; qualquer mudança de comportamento do algoritmo deve
# quebrar estes testes.


def test_derive_bate_com_valores_fixados() -> None:
    assert derive(0, "") == 1786884285633530058
    assert derive(1, "a") == 9243798235275095992
    assert derive(2**64 - 1, "t:x") == 5595448002866374418


def test_hierarquia_de_seeds_bate_com_valores_fixados() -> None:
    table_seed = seed_table(ROOT_SEED, "usuarios")
    column_seed = seed_column(table_seed, "cpf")
    assert table_seed == 5754506390876170851
    assert column_seed == 15938991699399409319
    assert seed_chunk(column_seed, 0) == 13918580507376032017
    assert seed_chunk(column_seed, 7) == 9689138865138785573
    assert seed_relation(table_seed, "pedidos") == 6774808792288788424
    assert seed_llm(column_seed, 777) == 15155425353873649086


def test_derive_e_deterministico_e_sensivel_ao_rotulo() -> None:
    assert derive(123, "c:cpf") == derive(123, "c:cpf")
    assert derive(123, "c:cpf") != derive(123, "c:nome")
    assert derive(123, "c:cpf") != derive(124, "c:cpf")


def test_mix_bate_com_valores_fixados() -> None:
    valores = np.array([0, 1, 2**63, 2**64 - 1, 123456789], dtype=np.uint64)
    esperado = np.array(
        [
            0,
            6238072747940578789,
            2720858781877447050,
            13029008266876403067,
            17445968401720671584,
        ],
        dtype=np.uint64,
    )
    assert np.array_equal(mix(valores), esperado)


def test_draw_u64_bate_com_valores_fixados() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "cpf")
    rows = np.array([0, 1, 2, 3, 4], dtype=np.int64)
    esperado = np.array(
        [
            12929826011346922964,
            4319798566831638143,
            4470148742535807714,
            520493338389473043,
            8062812603572778399,
        ],
        dtype=np.uint64,
    )
    assert np.array_equal(draw_u64(column_seed, rows, 2), esperado)


# --- comportamento do sorteio por célula


def test_draw_u64_e_puro_e_nao_depende_de_estado() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "cpf")
    rows = np.array([10, 20, 30], dtype=np.int64)
    assert np.array_equal(draw_u64(column_seed, rows, 5), draw_u64(column_seed, rows, 5))


def test_draw_u64_varia_por_slot_e_por_coluna() -> None:
    table_seed = seed_table(ROOT_SEED, "usuarios")
    column_seed = seed_column(table_seed, "cpf")
    outra_coluna_seed = seed_column(table_seed, "nome")
    rows = np.array([1, 2, 3], dtype=np.int64)
    assert not np.array_equal(draw_u64(column_seed, rows, 2), draw_u64(column_seed, rows, 3))
    assert not np.array_equal(draw_u64(column_seed, rows, 2), draw_u64(outra_coluna_seed, rows, 2))


def test_uniform_esta_em_zero_um() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "cpf")
    rows = np.arange(0, 50_000, dtype=np.int64)
    valores = uniform(column_seed, rows, 3)
    assert valores.min() >= 0.0
    assert valores.max() < 1.0
    assert valores.dtype == np.float64


def test_integers_respeita_limites_inclusive_exclusivo() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "idade")
    rows = np.arange(0, 10_000, dtype=np.int64)
    valores = integers(column_seed, rows, 4, 10, 20)
    assert valores.min() == 10
    assert valores.max() == 19
    assert valores.dtype == np.int64


def test_integers_com_faixa_de_tamanho_um_e_sempre_lo() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "idade")
    rows = np.arange(0, 100, dtype=np.int64)
    valores = integers(column_seed, rows, 4, 7, 8)
    assert np.all(valores == 7)


def test_integers_rejeita_faixa_vazia_ou_invertida() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "idade")
    rows = np.array([0], dtype=np.int64)
    with pytest.raises(ValueError, match="hi > lo"):
        integers(column_seed, rows, 4, 10, 10)
    with pytest.raises(ValueError, match="hi > lo"):
        integers(column_seed, rows, 4, 10, 5)


def test_integers_acima_de_2_elevado_53_usa_rejeicao_de_lemire() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "id_grande")
    rows = np.arange(0, 20_000, dtype=np.int64)
    hi = 2**60
    valores = integers(column_seed, rows, 6, 0, hi)
    assert valores.min() >= 0
    assert valores.max() < hi
    assert valores.dtype == np.int64
    # determinístico
    assert np.array_equal(valores, integers(column_seed, rows, 6, 0, hi))


def test_integers_grandes_nao_sao_todos_iguais() -> None:
    # guarda contra uma implementação de Lemire que degenerasse em uma
    # constante (ex.: usar sempre o mesmo slot em vez de crescer nas
    # rejeições, ou nunca amostrar a parte alta do produto de 128 bits).
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "id_grande")
    rows = np.arange(0, 5_000, dtype=np.int64)
    valores = integers(column_seed, rows, 6, 0, 2**60)
    assert len(set(valores.tolist())) > len(valores) // 2


def test_choice_delega_para_integers() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "categoria")
    rows = np.arange(0, 1000, dtype=np.int64)
    valores = choice(column_seed, rows, 7, 5)
    assert valores.min() >= 0
    assert valores.max() < 5
    assert np.array_equal(valores, integers(column_seed, rows, 7, 0, 5))


def test_normal_tem_media_e_desvio_esperados() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "peso")
    rows = np.arange(0, 500_000, dtype=np.int64)
    valores = normal(column_seed, rows, 8)
    assert math.isclose(float(valores.mean()), 0.0, abs_tol=0.02)
    assert math.isclose(float(valores.std()), 1.0, rel_tol=0.02)


def test_seed_llm_e_estavel_e_independente_de_chunk_size() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "bio")
    assert seed_llm(column_seed, 777) == seed_llm(column_seed, 777)
    # depende só da linha global, não de como ela foi agrupada em chunks
    assert seed_llm(column_seed, 42) != seed_llm(column_seed, 43)


def test_slots_reservados_sao_indices_validos() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "cpf")
    rows = np.array([0, 1, 2], dtype=np.int64)
    assert NULL_SLOT == 0
    assert INVALID_SLOT == 1
    assert FIRST_FREE_SLOT == 2
    assert LAST_FREE_SLOT == 63
    assert FIRST_REJECTION_SLOT == 64
    # slots reservados são só uma convenção de uso; draw_u64/uniform aceitam
    # qualquer um deles como um slot comum.
    for slot in (NULL_SLOT, INVALID_SLOT, FIRST_FREE_SLOT, LAST_FREE_SLOT, FIRST_REJECTION_SLOT):
        valores = uniform(column_seed, rows, slot)
        assert valores.shape == rows.shape


def test_random_seed_esta_no_intervalo_e_varia() -> None:
    valores = {random_seed() for _ in range(20)}
    assert all(0 <= valor < 2**63 for valor in valores)
    assert len(valores) > 1


# --- Draws: acesso O(1) por linha, independente de chunk_size (§8, critério 9)


def test_draws_com_indices_nao_contiguos_bate_com_lote_contiguo() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "cpf")
    linhas_esparsas = np.array([5, 1_000_000, 42], dtype=np.int64)
    isoladas = Draws(column_seed, linhas_esparsas).uniform(2)

    lote_contiguo = np.arange(0, 1_000_001, dtype=np.int64)
    resultado_do_lote = Draws(column_seed, lote_contiguo).uniform(2)

    assert np.array_equal(isoladas, resultado_do_lote[linhas_esparsas])


def test_draws_e_independente_do_tamanho_do_chunk() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "cpf")
    todas_as_linhas = np.arange(0, 10_000, dtype=np.int64)
    em_um_lote_so = Draws(column_seed, todas_as_linhas).uniform(2)

    em_lotes_de_mil = np.concatenate(
        [
            Draws(column_seed, todas_as_linhas[inicio : inicio + 1000]).uniform(2)
            for inicio in range(0, 10_000, 1000)
        ]
    )

    assert np.array_equal(em_um_lote_so, em_lotes_de_mil)


def test_recalcular_uma_linha_isolada_bate_com_o_lote() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "cpf")
    linha_isolada = Draws(column_seed, np.array([777], dtype=np.int64)).uniform(2)

    lote = np.arange(0, 10_000, dtype=np.int64)
    valor_no_lote = Draws(column_seed, lote).uniform(2)[777]

    assert linha_isolada[0] == valor_no_lote


def test_draws_integers_choice_e_normal_tem_o_tamanho_de_rows() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "cpf")
    rows = np.array([1, 2, 3, 4, 5, 6, 7], dtype=np.int64)
    draws = Draws(column_seed, rows)
    assert draws.integers(3, 0, 100).shape == rows.shape
    assert draws.choice(4, 10).shape == rows.shape
    assert draws.normal(5).shape == rows.shape


# --- qui-quadrado (DD-00 §8, critério 10): amostra grande, marcado `slow`
# para não rodar no gate padrão.


def _regularized_upper_incomplete_gamma(a: float, x: float) -> float:
    """Q(a, x) sem depender de scipy (ausente das dependências do projeto).

    Série (x < a+1) e fração contínua de Lentz (x >= a+1), o método clássico
    de Numerical Recipes. Validado contra o caso fechado do qui-quadrado com
    2 graus de liberdade (sf = exp(-x/2)) e contra tabelas de qui-quadrado
    conhecidas antes deste teste ser escrito.
    """
    if x <= 0:
        return 1.0
    if x < a + 1:
        term = 1.0 / a
        total = term
        ap = a
        for _ in range(500):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-14:
                break
        return 1.0 - total * math.exp(-x + a * math.log(x) - math.lgamma(a))

    tiny = 1e-300
    b = x + 1 - a
    c = 1 / tiny
    d = 1 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - math.lgamma(a)) * h


def _chi_squared_p_value(observed: NDArray[np.int64], expected_per_bin: float) -> float:
    statistic = float(np.sum((observed - expected_per_bin) ** 2 / expected_per_bin))
    degrees_of_freedom = observed.size - 1
    return _regularized_upper_incomplete_gamma(degrees_of_freedom / 2, statistic / 2)


@pytest.mark.slow
def test_uniform_passa_no_teste_qui_quadrado() -> None:
    column_seed = seed_column(seed_table(ROOT_SEED, "usuarios"), "cpf")
    num_samples = 1_000_000
    num_bins = 100
    rows = np.arange(0, num_samples, dtype=np.int64)
    valores = uniform(column_seed, rows, 9)

    observed, _ = np.histogram(valores, bins=num_bins, range=(0.0, 1.0))
    expected_per_bin = num_samples / num_bins

    p_value = _chi_squared_p_value(observed, expected_per_bin)
    assert p_value > 0.001
