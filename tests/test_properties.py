"""Группа C: property-based (docs/money.md §6.C) и сходимость каналов из DoD."""

from __future__ import annotations

import random
from decimal import Decimal as D

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from smeta_core import (
    Category,
    PositionData,
    calculate_estimate,
    format_money,
    from_bp,
    from_kop,
    from_milli,
    to_bp,
    to_kop,
    to_milli,
)

from conftest import excel_round, position_st, price_st, qty_price_st, qty_st, rate_st

SETTINGS = settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

estimate_st = st.tuples(st.lists(position_st(), max_size=60), rate_st, rate_st)


def _parse_shown(text: str) -> D:
    return D(text.replace(",", "."))


@SETTINGS
@given(estimate_st)
def test_c1_total_equals_sum_of_shown_lines(data):
    positions, work, material = data
    result = calculate_estimate(positions, work, material)
    shown = sum(
        (_parse_shown(format_money(line.total)) for line in result.lines), D("0.00")
    )
    assert shown == _parse_shown(format_money(result.total))


@SETTINGS
@given(estimate_st)
def test_c2_subtotal_plus_markup_equals_total(data):
    positions, work, material = data
    result = calculate_estimate(positions, work, material)
    assert result.subtotal + result.markup == result.total


@SETTINGS
@given(estimate_st)
def test_c3_every_money_value_has_exponent_minus_two(data):
    positions, work, material = data
    result = calculate_estimate(positions, work, material)
    values = [result.subtotal, result.markup, result.total]
    for line in result.lines:
        values += [line.base, line.total]
    assert all(value.as_tuple().exponent == -2 for value in values)


@SETTINGS
@given(st.lists(position_st(), max_size=60))
def test_c4_zero_rate_means_total_equals_subtotal(positions):
    result = calculate_estimate(positions, D("0.00"), D("0.00"))
    assert result.total == result.subtotal
    assert result.markup == D("0.00")


@SETTINGS
@given(st.lists(position_st(), max_size=40), qty_st, rate_st)
def test_c5_adding_a_priced_position_increases_the_total(positions, qty, rate):
    extra = PositionData(Category.WORK, "добавка", qty, D("1000.00"))
    before = calculate_estimate(positions, rate, rate).total
    after = calculate_estimate(list(positions) + [extra], rate, rate).total
    assert after > before


@SETTINGS
@given(
    # Обмен местами возможен, только если оба значения проходят обе валидации:
    # цена ≤ 2 знаков, количество ≤ 99 999.999. Потолок 20 000 держит
    # произведение под потолком суммы строки.
    st.integers(min_value=1, max_value=2_000_000).map(lambda k: D(k).scaleb(-2)),
    st.integers(min_value=1, max_value=2_000_000).map(lambda k: D(k).scaleb(-2)),
    rate_st,
)
def test_c6_qty_and_price_are_symmetric(a, b, rate):
    straight = calculate_estimate(
        [PositionData(Category.WORK, "x", a, b)], rate, rate
    ).total
    swapped = calculate_estimate(
        [PositionData(Category.WORK, "x", b, a)], rate, rate
    ).total
    assert straight == swapped


@SETTINGS
@given(qty_price_st(), rate_st)
def test_c8_excel_parity_on_both_cascades(qty_price, rate):
    """Формулы =ROUND(C*D;2) и =ROUND(E*(1+B1/100);2) обязаны дать то же самое."""
    qty, price = qty_price
    result = calculate_estimate(
        [PositionData(Category.WORK, "x", qty, price)], rate, rate
    )
    line = result.lines[0]

    excel_base = excel_round(float(qty) * float(price))
    excel_total = excel_round(float(excel_base) * (1.0 + float(rate) / 100.0))

    assert excel_base == line.base
    assert excel_total == line.total


@SETTINGS
@given(qty_st, price_st, rate_st)
def test_c9_storage_round_trip_is_lossless(qty, price, rate):
    assert from_milli(to_milli(qty)) == qty
    assert from_kop(to_kop(price)) == price
    assert from_bp(to_bp(rate)) == rate


def test_dod_ten_thousand_estimates_three_channels_agree():
    """DoD Sprint 1: на 10 000 случайных смет три канала сходятся до копейки.

    Каналы: Telegram (/list), сводка (/estimates) и XLSX. Excel-канал считается
    эмулятором excel_round по тем же формулам, что записываются в файл.
    """
    rng = random.Random(20260729)

    for _ in range(10_000):
        rate_work = D(rng.randrange(0, 10_000)).scaleb(-2)
        rate_material = D(rng.randrange(0, 10_000)).scaleb(-2)
        positions = []
        for index in range(rng.randint(1, 25)):
            qty = D(rng.randrange(1, 100_000_000)).scaleb(-3)
            price_cap = min(999_999_999, int(D("500000000") / qty * 100))
            positions.append(
                PositionData(
                    category=rng.choice([Category.WORK, Category.MATERIAL]),
                    name=f"поз-{index}",
                    qty=qty,
                    price=D(rng.randrange(0, price_cap + 1)).scaleb(-2),
                )
            )

        result = calculate_estimate(positions, rate_work, rate_material)

        # Канал 1: Telegram — человек складывает то, что видит.
        telegram = sum(
            (_parse_shown(format_money(line.total)) for line in result.lines),
            D("0.00"),
        )
        # Канал 2: сводка /estimates — одно число из того же расчёта.
        summary = result.total
        # Канал 3: XLSX — живые формулы, пересчитанные по правилам Excel.
        excel = D("0.00")
        for line in result.lines:
            rate = (
                rate_work
                if line.position.category == Category.WORK
                else rate_material
            )
            base = excel_round(float(line.position.qty) * float(line.position.price))
            excel += excel_round(float(base) * (1.0 + float(rate) / 100.0))

        assert telegram == summary == excel
