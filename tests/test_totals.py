"""Группа B: инварианты итога (docs/money.md §6.B)."""

from decimal import Decimal as D

import pytest

from smeta_core import (
    Category,
    PositionData,
    calculate_estimate,
    check_rate,
    format_money,
)

W = D("6.00")


def test_b1_total_is_sum_of_line_totals():
    positions = [
        PositionData(Category.WORK, "Побелка", D("1.5"), D("100.10")),
        PositionData(Category.WORK, "Стяжка", D("2.5"), D("100.10")),
        PositionData(Category.MATERIAL, "Гвозди", D("1000"), D("0.37")),
    ]
    result = calculate_estimate(positions, W, W)
    assert sum(line.total for line in result.lines) == result.total


def test_b1_screen_sum_equals_screen_total():
    """То, что человек складывает глазами, обязано сходиться с «Итого»."""
    positions = [
        PositionData(Category.WORK, "Побелка", D("1.5"), D("100.10")),
        PositionData(Category.WORK, "Стяжка", D("2.5"), D("100.10")),
    ]
    result = calculate_estimate(positions, W, W)
    on_screen = [D(format_money(line.total).replace(",", ".")) for line in result.lines]
    assert sum(on_screen) == D(format_money(result.total).replace(",", "."))


def test_b2_markup_is_a_difference_not_a_product():
    positions = [PositionData(Category.WORK, "x", D("1"), D("0.01"))] * 100
    result = calculate_estimate(positions, W, W)
    assert result.markup == result.total - result.subtotal
    # Умножением получилось бы 0.06 — и итог перестал бы сходиться со строками.
    assert result.markup == D("0.00")


def test_b3_empty_estimate():
    result = calculate_estimate([], W, W)
    assert (result.subtotal, result.markup, result.total) == (
        D("0.00"), D("0.00"), D("0.00"),
    )
    assert result.lines == ()


def test_b4_zero_price_is_allowed():
    result = calculate_estimate(
        [PositionData(Category.MATERIAL, "Подарок", D("3"), D("0.00"))], W, W
    )
    assert result.lines[0].base == D("0.00")
    assert result.total == D("0.00")


def test_b5_ten_thousand_kopek_lines():
    """Семантика «Σ построчных копеек» зафиксирована: 100.00, а не 106.00."""
    positions = [PositionData(Category.WORK, "x", D("1"), D("0.01"))] * 10_000
    result = calculate_estimate(positions, W, W)
    assert result.total == D("100.00")
    assert result.subtotal == D("100.00")


def test_b6_separate_rates_per_category():
    positions = [
        PositionData(Category.WORK, "Работа", D("1"), D("1000.00")),
        PositionData(Category.MATERIAL, "Материал", D("1"), D("1000.00")),
    ]
    result = calculate_estimate(positions, D("10.00"), D("0.00"))
    assert result.lines[0].total == D("1100.00")
    assert result.lines[1].total == D("1000.00")
    assert result.total == D("2100.00")
    assert result.markup == D("100.00")


def test_b7_line_ceiling_is_enforced():
    """Отклонение от money.md §6.B7 — обосновано ADR-003.

    Спецификация §1.2 разрешает qty*price до ~10^12, но §3.4 гарантирует
    паритет с Excel только ниже 10^9. Домен закрывает противоречие отказом.
    """
    positions = [PositionData(Category.WORK, "x", D("99999.999"), D("9999999.99"))]
    with pytest.raises(ValueError, match="превышает потолок"):
        calculate_estimate(positions, D("99.99"), D("99.99"))


def test_b7_largest_accepted_line():
    positions = [PositionData(Category.WORK, "x", D("99999.999"), D("5000.00"))]
    result = calculate_estimate(positions, D("0.00"), D("0.00"))
    assert result.total == D("499999995.00")
    assert result.total.as_tuple().exponent == -2


def test_b8_order_does_not_change_the_total():
    positions = [
        PositionData(Category.WORK, "a", D("1.234"), D("56.78")),
        PositionData(Category.MATERIAL, "b", D("9.876"), D("54.32")),
        PositionData(Category.WORK, "c", D("0.001"), D("0.01")),
    ]
    forward = calculate_estimate(positions, W, D("3.00")).total
    backward = calculate_estimate(positions[::-1], W, D("3.00")).total
    assert forward == backward


@pytest.mark.parametrize("bad", ["-1", "100", "6.005"])
def test_d10_rate_bounds(bad):
    with pytest.raises(ValueError):
        check_rate(D(bad))
