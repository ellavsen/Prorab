"""Группа E: разбор строк ввода и слияние дублей."""

from decimal import Decimal as D

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smeta_core import (
    AmbiguousLine,
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


@pytest.mark.parametrize(
    "raw, expected",
    [("точка", "точка"), ("точек", "точка"), ("Точки", "точка"),
     ("смена", "смена"), ("день", "смена"), ("дня", "смена"), ("дней", "смена"),
     # Тара канона не получает намеренно: в мешке может быть и 25 кг, и 50.
     ("мешок", ""), ("рулон", ""), ("лист", ""), ("упаковка", ""),
     # «т.» — тонна, и добавление «точки» не имеет права это переехать.
     ("т.", "т"), ("тонн", "т")],
)
def test_work_units_are_canon_and_packaging_is_not(raw, expected):
    """Точка — единица электромонтажа, смена — повремёнки (ADR-016).

    Пустой канон там, где единица есть, теряет данные: цену «за точку» не
    отличить от цены «за штуку», и справочник цен их не сопоставит.
    """
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


# --- Устойчивость парсера: запятая внутри наименования (ADR-011) ---

@pytest.mark.parametrize(
    "line, name, qty, price",
    [
        ("Гвозди 3,5 мм, 100, 20", "Гвозди 3,5 мм", D("100"), D("20.00")),
        ("Уголок 30, оцинкованный, 5, 100", "Уголок 30, оцинкованный", D("5"), D("100.00")),
        ("Труба 20х20х1,5, 12, 340", "Труба 20х20х1,5", D("12"), D("340.00")),
        ('Плитка "Керама", 12.5, 890', 'Плитка "Керама"', D("12.5"), D("890.00")),
        ("Смесь, сухая, 3, 450", "Смесь, сухая", D("3"), D("450.00")),
    ],
)
def test_commas_inside_the_name_no_longer_break_the_parser(line, name, qty, price):
    position = parse_position_line(line, Category.MATERIAL)
    assert position.name == name
    assert position.qty == qty
    assert position.price == price


def test_name_is_kept_exactly_as_typed():
    """Мы не переписываем наименование: «3,5 мм» остаётся «3,5 мм»."""
    assert parse_position_line("Гвозди 3,5 мм, 100, 20", Category.MATERIAL).name == "Гвозди 3,5 мм"


@pytest.mark.parametrize(
    "line, qty",
    [
        ("Гвозди,1000,20", D("1000")),        # без пробелов — слитое чтение недопустимо
        ("Побелка, 40.5, 1200", D("40.5")),   # точка всегда однозначна
        ("Побелка, 150 м2, 3000", D("150")),
    ],
)
def test_unambiguous_lines_are_not_questioned(line, qty):
    assert parse_position_line(line, Category.WORK).qty == qty


@pytest.mark.parametrize(
    "line, plain_qty, merged_qty",
    [
        ("Побелка, 150,5, 3000", D("5"), D("150.5")),
        ("Смесь М-150, 40,5 кг, 320", D("5"), D("40.5")),
    ],
)
def test_genuinely_ambiguous_lines_are_reported_with_both_readings(line, plain_qty, merged_qty):
    with pytest.raises(AmbiguousLine) as caught:
        parse_position_line(line, Category.MATERIAL)
    assert caught.value.plain.qty == plain_qty
    assert caught.value.merged.qty == merged_qty


def test_ambiguity_needs_the_money_to_differ():
    """Если суммы совпадают, различие только в тексте имени — не переспрашиваем."""
    position = parse_position_line("Гвозди 3,5 мм, 100, 20", Category.MATERIAL)
    assert position.qty == D("100")
    assert position.price == D("20.00")


@given(
    # Запятые из имени вырезаются ниже, поэтому годным должно быть то, что
    # останется: имя «,» после замены превращается в пустое и валидным не будет.
    st.text(min_size=1, max_size=60).filter(
        lambda s: s.replace(",", " ").strip() and "\n" not in s
    ),
    st.integers(min_value=1, max_value=99_999_999),
    st.integers(min_value=0, max_value=999_999_999),
)
@settings(max_examples=200, deadline=None)
def test_round_trip_any_valid_position(name, qty_milli, price_kop):
    """Собранная из валидных частей строка разбирается обратно в них же."""
    qty, price = D(qty_milli).scaleb(-3), D(price_kop).scaleb(-2)
    line = f"{name.replace(',', ' ')}, {qty}, {price}"

    position = parse_position_line(line, Category.WORK)
    assert position.qty == qty
    assert position.price == price


def test_decimal_reading_wins_when_the_plain_one_is_invalid():
    """«Побелка, 1,0, 3000»: как поля — количество 0, что запрещено; как дробь — 1.0."""
    position = parse_position_line("Побелка, 1,0, 3000", Category.WORK)
    assert position.qty == D("1.0")
    assert position.name == "Побелка"


def test_when_neither_reading_works_the_error_is_about_the_fields():
    with pytest.raises(ValueError, match="нужно 3"):
        parse_position_line("1,5", Category.WORK)


# --- Единицы: канон best-effort, блокировка только для подстановки цены (ADR-015) ---

def test_canonical_unit_is_derived_from_what_was_said():
    from smeta_core import unit_decision

    assert unit_decision("", "м2") == "м²"
    assert unit_decision("м.п.", "погонных") == "м.п."
    assert unit_decision("", "мешков") == ""      # упаковка, канона нет


def test_an_unknown_unit_does_not_affect_the_money():
    """Обоснование ADR-015: единица в арифметике не участвует.

    «20 мешков по 350» даёт 7000 при любом каноне, поэтому блокировать ввод
    из-за незнакомой единицы незачем.
    """
    from smeta_core import calculate_estimate

    bags = PositionData(Category.MATERIAL, "Цемент", D("20"), D("350"),
                        unit="", unit_spoken="мешков")
    kilos = PositionData(Category.MATERIAL, "Цемент", D("20"), D("350"), unit="кг")
    assert (calculate_estimate([bags], D("0"), D("0")).total
            == calculate_estimate([kilos], D("0"), D("0")).total == D("7000.00"))


def test_price_may_be_substituted_only_for_a_confirmed_unit():
    """Единственный опасный случай: цену подставляет система, а не человек."""
    from smeta_core import can_substitute_price

    assert can_substitute_price("кг") is True
    assert can_substitute_price("") is False
    # Флаг выключает проверку без правки кода.
    assert can_substitute_price("", blocking_enabled=False) is True
