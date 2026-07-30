"""Группа D: валидация ввода (docs/money.md §6.D)."""

from decimal import Decimal as D

import pytest

from smeta_core import (
    Category,
    PositionData,
    check_name,
    check_price,
    merge_duplicates,
    normalize_unit,
    parse_position_line,
    parse_price,
    parse_quantity,
    parse_rate,
)


def test_d1_price_with_three_decimals_is_rejected():
    with pytest.raises(ValueError, match="не более 2 знаков"):
        parse_price("12.345")


def test_d2_quantity_with_four_decimals_is_rejected():
    with pytest.raises(ValueError, match="не более 3 знаков"):
        parse_quantity("1.2345")


@pytest.mark.parametrize("bad", ["0", "0.000", "-5"])
def test_d3_non_positive_quantity_is_rejected(bad):
    with pytest.raises(ValueError):
        parse_quantity(bad)


def test_d4_negative_price_is_rejected():
    with pytest.raises(ValueError, match="отрицательные"):
        parse_price("-1")


def test_d5_comma_is_a_decimal_separator():
    assert parse_quantity("40,5") == D("40.5")


@pytest.mark.parametrize("bad", ["1e3", "NaN", "nan", "Infinity", "-Infinity", "0x10"])
def test_d6_decimal_accepts_this_garbage_but_we_do_not(bad):
    with pytest.raises(ValueError):
        parse_quantity(bad)
    with pytest.raises(ValueError):
        parse_price(bad)


def test_d7_quantity_above_the_limit_is_rejected():
    with pytest.raises(ValueError, match="99999,999"):
        parse_quantity("100000")


def test_d8_merge_overflow_is_rejected_and_leaves_input_untouched():
    first = PositionData(Category.MATERIAL, "Песок", D("60000"), D("100.00"))
    second = PositionData(Category.MATERIAL, "Песок", D("50000"), D("100.00"))
    with pytest.raises(ValueError, match="превышает лимит"):
        merge_duplicates([first, second])
    assert first.qty == D("60000")
    assert second.qty == D("50000")


@pytest.mark.parametrize("bad", ["", "   ", "x" * 201])
def test_d9_bad_names_are_rejected(bad):
    with pytest.raises(ValueError):
        check_name(bad)


def test_d9_name_of_exactly_200_is_accepted():
    assert check_name("x" * 200) == "x" * 200


def test_price_above_the_limit_is_rejected():
    with pytest.raises(ValueError, match="9999999,99"):
        parse_price("10000000")


def test_position_cannot_be_constructed_invalid():
    """Невалидной PositionData не существует — валидация в самом типе."""
    with pytest.raises(ValueError):
        PositionData(Category.WORK, "x", D("0"), D("10.00"))
    with pytest.raises(ValueError):
        PositionData(Category.WORK, "", D("1"), D("10.00"))


@pytest.mark.parametrize("empty", ["", "   "])
def test_empty_number_is_reported_as_missing(empty):
    with pytest.raises(ValueError, match="не указано"):
        parse_quantity(empty)


def test_negative_price_reaching_the_checker_directly_is_rejected():
    with pytest.raises(ValueError, match="отрицательные"):
        check_price(D("-0.01"))


@pytest.mark.parametrize("raw, expected", [("6", D("6.00")), ("6,5", D("6.50")), ("0", D("0.00"))])
def test_rate_parsing(raw, expected):
    assert parse_rate(raw) == expected


@pytest.mark.parametrize("bad", ["-1", "100", "6.005", "nan"])
def test_bad_rate_is_rejected(bad):
    with pytest.raises(ValueError):
        parse_rate(bad)


def test_canonical_unit_stays_canonical():
    assert normalize_unit("м²") == "м²"
    assert normalize_unit("час") == "час"


def test_quantity_field_without_any_digit():
    with pytest.raises(ValueError):
        parse_position_line("Побелка, много, 3000", Category.WORK)


def test_decimal_comma_in_the_middle_field_is_caught_not_silently_misread():
    """«Побелка, 150,5, 3000» — четыре поля. Раньше молча читалось как qty=150."""
    with pytest.raises(ValueError, match="получено полей: 4"):
        parse_position_line("Побелка, 150,5, 3000", Category.WORK)
