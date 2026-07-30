"""Группа A: округление (docs/money.md §6.A)."""

from decimal import Decimal as D

import pytest

from smeta_core import Category, PositionData, calculate_estimate, round2

W = D("6.00")


def line(qty: str, price: str, rate: D = W) -> tuple[D, D]:
    result = calculate_estimate(
        [PositionData(Category.WORK, "x", D(qty), D(price))], rate, rate
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
