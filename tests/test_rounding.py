"""Группа A: округление (docs/money.md §6.A)."""

from decimal import Decimal as D

import pytest

from smeta_core import (
    Category,
    PositionData,
    RateBase,
    calculate_estimate,
    round2,
)

W = D("6.00")


def line(qty: str, price: str, rate: D = W, base=RateBase.COST) -> tuple[D, D]:
    result = calculate_estimate(
        [PositionData(Category.WORK, "x", D(qty), D(price))], rate, rate, base
    )
    return result.lines[0].base, result.lines[0].total


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0.005", "0.01"),      # A1 — HALF_UP, не банковское
        ("0.004999", "0.00"),   # A2
        ("0.015", "0.02"),      # A3
        ("2.675", "2.68"),      # A4 — классическая float-ловушка, у нас Decimal
    ],
)
def test_round2_half_up(value, expected):
    assert round2(D(value)) == D(expected)


def test_a5_result_always_has_two_decimals():
    assert round2(D("1.1")).as_tuple().exponent == -2
    assert str(round2(D("1.1"))) == "1.10"


def test_a6_base_on_the_half_kopek_boundary():
    base, _ = line("0.5", "0.01")       # ровно 0.005
    assert base == D("0.01")


def test_a7_base_rounds_exact_product():
    base, _ = line("0.007", "5.00")     # ровно 0.035
    assert base == D("0.04")


def test_a8_line_with_markup():
    _, total = line("1", "100.00")
    assert total == D("106.00")


def test_a9_markup_disappears_on_one_kopek():
    # 0.01 * 1.06 = 0.0106 -> 0.01. Наценка «исчезает» — поведение осознанное.
    _, total = line("1", "0.01")
    assert total == D("0.01")


def test_a10_second_cascade_boundary():
    _, total = line("1", "0.50", D("1.00"))   # 0.50 * 1.01 = 0.505
    assert total == D("0.51")


# --- Процент от суммы заказчику: gross-up вместо наценки сверху ---


@pytest.mark.parametrize(
    "executor_price, invoiced",
    [("250", "265.96"), ("800", "851.06"), ("1200", "1276.60")],
)
def test_a14_the_percent_can_be_withheld_from_the_invoiced_sum(executor_price, invoiced):
    """Три строки из настоящей сметы прораба. 6% — условие договора заказчика.

    Процент удерживается ИЗ выставленной суммы, поэтому её тянут вверх, чтобы
    исполнитель получил ровно свою цену: 250 / 0,94, а не 250 × 1,06.
    """
    _, total = line("1", executor_price, base=RateBase.PRICE)
    assert total == D(invoiced)


def test_a15_on_one_line_the_withheld_part_is_the_percent_of_the_gross():
    """Проверка, по которой это опознаётся: надбавка считается от выставленного."""
    _, total = line("1", "250", base=RateBase.PRICE)
    assert total - D("250") == round2(total * D("0.06")) == D("15.96")


def test_a16_the_two_bases_disagree_and_that_is_the_whole_point():
    """При умножении на 1,06 исполнитель недополучает с каждой строки."""
    assert line("1", "800", base=RateBase.COST)[1] == D("848.00")
    assert line("1", "800", base=RateBase.PRICE)[1] == D("851.06")


def test_a17_the_markup_still_disappears_on_one_kopeck():
    """A9 остаётся верным при обоих основаниях: 0,01 / 0,94 = 0,0106 -> 0,01."""
    assert line("1", "0.01", base=RateBase.PRICE)[1] == D("0.01")


def test_a18_the_ceiling_is_lower_when_the_percent_comes_off_the_sum():
    """Ставка там делит: 50% дают ×2, 90% — ×10, 99,99% — ×10 000.

    Половина удерживает множитель в тех же ×2, под которые посчитан бюджет
    15 значащих цифр в money.md §3.4. Наценке сверху этот потолок не нужен —
    её множитель не превышает ×1,9999 при любой допустимой ставке.
    """
    assert line("1", "100", D("60.00"))[1] == D("160.00")
    with pytest.raises(ValueError, match="0…50,00%"):
        line("1", "100", D("60.00"), base=RateBase.PRICE)


# --- Деление «за всё»: только по явной просьбе (ADR-012) ---

def test_a11_unit_price_divides_and_rounds():
    from smeta_core import unit_price
    assert unit_price(D("30000.00"), D("7")) == D("4285.71")


def test_a12_division_does_not_come_back_to_the_same_sum():
    """Причина, по которой «за всё» схлопывается, а не делится.

    Человек назвал 30 000; разделив и умножив обратно, получаем 29 999,97.
    Три копейки — это ровно тот баг доверия, ради которого писался Sprint 1.
    """
    from smeta_core import Category, PositionData, calculate_estimate, unit_price

    each = unit_price(D("30000.00"), D("7"))
    restored = calculate_estimate(
        [PositionData(Category.WORK, "Покраска", D("7"), each)], D("0"), D("0")
    ).subtotal
    assert restored == D("29999.97")
    assert D("30000.00") - restored == D("0.03")


def test_a13_division_that_is_exact_loses_nothing():
    from smeta_core import Category, PositionData, calculate_estimate, unit_price

    each = unit_price(D("30000.00"), D("100"))
    restored = calculate_estimate(
        [PositionData(Category.WORK, "Покраска", D("100"), each)], D("0"), D("0")
    ).subtotal
    assert (each, restored) == (D("300.00"), D("30000.00"))
