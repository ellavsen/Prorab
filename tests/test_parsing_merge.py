"""Группа E: разбор строк ввода и слияние дублей."""

from decimal import Decimal as D

import pytest

from smeta_core import (
    Category,
    PositionData,
    merge_duplicates,
    normalize_unit,
    parse_position_line,
)


def test_material_line():
    position = parse_position_line("Гвозди, 1000, 20", Category.MATERIAL)
    assert position.name == "Гвозди"
    assert position.qty == D("1000")
    assert position.price == D("20.00")
    assert position.category == Category.MATERIAL


def test_work_line_with_unit():
    position = parse_position_line("Побелка, 150 м2, 3000", Category.WORK)
    assert position.qty == D("150")
    assert position.price == D("3000.00")
    assert position.unit == "м²"


def test_unit_is_optional():
    assert parse_position_line("Побелка, 150, 3000", Category.WORK).unit == ""


def test_unknown_unit_is_dropped_not_fatal():
    position = parse_position_line("Побелка, 150 квадратов, 3000", Category.WORK)
    assert position.qty == D("150")
    assert position.unit == ""


@pytest.mark.parametrize(
    "raw, expected",
    [("м2", "м²"), ("М2", "м²"), ("пм", "м.п."), ("шт.", "шт"), ("кв.м", "м²"),
     ("ч", "час"), ("бананов", "")],
)
def test_unit_normalization(raw, expected):
    assert normalize_unit(raw) == expected


def test_too_few_fields():
    with pytest.raises(ValueError, match="получено полей: 2"):
        parse_position_line("Гвозди, 1000", Category.MATERIAL)


def test_merge_sums_quantities_of_identical_positions():
    positions = [
        PositionData(Category.MATERIAL, "Гвозди", D("100"), D("20.00")),
        PositionData(Category.WORK, "Побелка", D("50"), D("300.00")),
        PositionData(Category.MATERIAL, "Гвозди", D("250"), D("20.00")),
    ]
    merged = merge_duplicates(positions)
    assert len(merged) == 2
    assert merged[0].name == "Гвозди" and merged[0].qty == D("350")
    assert merged[1].name == "Побелка"


def test_merge_keeps_different_prices_apart():
    positions = [
        PositionData(Category.MATERIAL, "Гвозди", D("100"), D("20.00")),
        PositionData(Category.MATERIAL, "Гвозди", D("100"), D("21.00")),
    ]
    assert len(merge_duplicates(positions)) == 2


def test_merge_keeps_categories_apart():
    positions = [
        PositionData(Category.MATERIAL, "Стяжка", D("1"), D("10.00")),
        PositionData(Category.WORK, "Стяжка", D("1"), D("10.00")),
    ]
    assert len(merge_duplicates(positions)) == 2


def test_merge_of_nothing():
    assert merge_duplicates([]) == ()
