"""Группа H: нормализация наименований и тары (ADR-017).

Здесь проверяется ровно одно свойство и его границы: две записи одного
материала обязаны совпасть, а две записи РАЗНЫХ материалов обязаны разойтись.
Второе важнее первого — промах стоит подсказки, ложное совпадение стоит денег.
"""

import itertools

import pytest

from smeta_core import UNITS, normalize_unit
from smeta_prices import (
    FORM_GROUPS,
    FORMS,
    FormCollision,
    build_forms,
    fold,
    normalize_name,
    packaging_form,
    same_unit,
)

# --- Одна позиция, записанная по-разному ---


@pytest.mark.parametrize(
    "raw",
    ["цемент м500", "Цемент М500", "цемент  М-500", "ЦЕМЕНТ, М500", "цемент м500"],
)
def test_one_material_written_differently_gives_one_key(raw):
    assert normalize_name(raw) == normalize_name("цемент м500")


def test_latin_lookalikes_fold_to_cyrillic():
    """«M500» с латинской M и «М500» с кириллической — одно для человека."""
    assert normalize_name("цемент M500") == normalize_name("цемент М500")


def test_word_order_does_not_matter():
    assert normalize_name("плитка керамическая") == normalize_name("керамическая плитка")


def test_packaging_is_dropped_from_the_key():
    """«м500 мешок 50 кг» — это тот же м500, фасовка к имени не относится."""
    assert normalize_name("м500 мешок 50 кг") == normalize_name("м500")
    assert normalize_name("цемент 2 мешка") == normalize_name("цемент")


# --- Разные позиции, которые не имеют права слиться ---


def test_sizes_survive_normalization():
    """Самое дорогое ложное совпадение: 12 мм против 16 мм."""
    assert normalize_name("арматура 12 мм") != normalize_name("арматура 16 мм")
    assert normalize_name("уголок 30") != normalize_name("уголок 50")


def test_different_materials_do_not_collide():
    assert normalize_name("цемент м500") != normalize_name("цемент м400")
    assert normalize_name("плитка") != normalize_name("плинтус")


def test_a_name_made_only_of_packaging_keeps_its_words():
    """Иначе «мешок» и «рулон» стали бы одним пустым ключом."""
    assert normalize_name("мешок") != normalize_name("рулон")
    assert normalize_name("мешок") != ""


def test_empty_stays_empty():
    assert normalize_name("") == ""
    assert fold("  ") == ""


# --- Тара: закрытый словарь и его коллизии ---


def test_cases_of_one_packaging_word_fold_together():
    assert packaging_form("мешков") == packaging_form("мешок") == "мешок"
    assert packaging_form("листов") == "лист"
    assert packaging_form("бетон") == ""


def test_no_form_belongs_to_two_kinds_of_packaging():
    """Попарный прогон по всему словарю — то, чем ловится дубль «т.».

    Проверяется исходный список групп, а не собранный словарь: в словаре
    коллизия уже разрешилась бы молча, последней записью.
    """
    for left, right in itertools.combinations(FORM_GROUPS, 2):
        shared = set(left) & set(right)
        assert not shared, f"{left[0]} и {right[0]} делят словоформы: {sorted(shared)}"


def test_no_packaging_form_shadows_a_unit_of_the_core():
    """«литров» не должно оказаться формой «листа», и наоборот (ADR-016)."""
    for form in FORMS:
        assert not normalize_unit(form), f"{form!r} — единица ядра, а не тара"
    for unit in UNITS:
        assert unit not in FORMS


def test_a_collision_in_the_source_list_is_an_error_not_a_winner():
    with pytest.raises(FormCollision, match="мешков"):
        build_forms((("мешок", "мешков"), ("рулон", "мешков")))


def test_the_real_dictionary_builds():
    assert build_forms(FORM_GROUPS) == FORMS


# --- Сравнение единиц: чем можно подсказывать, а чем нельзя ---


@pytest.mark.parametrize(
    "left, right, expected",
    [
        (("кг", ""), ("кг", ""), True),            # канон совпал
        (("м²", ""), ("м.п.", ""), False),         # площадь против длины — никогда
        (("", "мешков"), ("", "мешок"), True),     # падежи одного слова
        (("", "мешок"), ("", "рулон"), False),     # разная тара
        (("", "мешок"), ("кг", ""), False),        # «350 за мешок» ≠ «350 за кг»
        (("", ""), ("", ""), False),               # не сказано ничего — не сравниваем
        (("", "штуковин"), ("", "штуковин"), True),  # буквально одно слово
        (("", "штуковин"), ("м²", ""), False),     # незнакомое слово против канона
    ],
)
def test_units_are_compared_by_canon_then_by_spoken_word(left, right, expected):
    assert same_unit(*left, *right) is expected


def test_a_spoken_unit_known_to_the_core_is_compared_by_its_canon():
    """«квадратов» ядро приводит к м², и сравнение идёт уже по канону."""
    assert same_unit("", "кв.м", "м²", "") is True
