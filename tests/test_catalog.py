"""Группа H: справочник позиций (ADR-017).

Справочник — факты: единица, категория, синонимы. Цены в нём нет ни одной, и
это проверяется по файлу, а не по обещанию.
"""

import json

import pytest

from smeta_core import UNITS
from smeta_prices import normalize_name
from smeta_prices.catalog import CATALOG, DATA, KINDS, CatalogError, Item, build, load


def raw_rows():
    return json.loads(DATA.read_text(encoding="utf-8"))


# --- Файл: то, что может разойтись молча ---


def test_the_catalog_holds_no_price_at_all():
    """DoD спринта: ни одной цены из справочника. Доказательство — поля файла."""
    for row in raw_rows():
        assert set(row) == {"name", "unit", "kind", "aliases"}, row["name"]


def test_the_catalog_is_big_enough_to_be_useful():
    assert len(CATALOG.items) >= 150


@pytest.mark.parametrize("item", CATALOG.items, ids=lambda item: item.name)
def test_every_unit_belongs_to_the_canon_of_the_core(item):
    """Своё написание единицы разъехалось бы с ядром на пустом месте."""
    assert item.unit in UNITS
    assert item.kind in KINDS


@pytest.mark.parametrize("item", CATALOG.items, ids=lambda item: item.name)
def test_every_item_finds_itself_by_its_own_name(item):
    """Round-trip: канон, прогнанный через нормализацию, ведёт к себе же."""
    assert CATALOG.find(item.name) is item
    assert CATALOG.index[normalize_name(item.name)] is item


@pytest.mark.parametrize("item", CATALOG.items, ids=lambda item: item.name)
def test_every_alias_leads_to_its_own_item(item):
    for alias in item.aliases:
        assert CATALOG.find(alias) is item, alias


def test_no_spelling_belongs_to_two_items():
    """Тот же класс ошибки, что дубль «т.», только на именах."""
    with pytest.raises(CatalogError, match="принадлежит"):
        build([
            {"name": "Цемент М500", "unit": "т", "kind": "material", "aliases": ["м500"]},
            {"name": "Смесь М500", "unit": "кг", "kind": "material", "aliases": ["м500"]},
        ])


def test_a_unit_outside_the_canon_is_refused():
    with pytest.raises(CatalogError, match="вне канона"):
        build([{"name": "Цемент", "unit": "мешок", "kind": "material", "aliases": []}])


def test_an_unknown_kind_is_refused():
    with pytest.raises(CatalogError, match="неизвестна"):
        build([{"name": "Цемент", "unit": "т", "kind": "товар", "aliases": []}])


def test_the_shipped_file_loads():
    assert load().index == CATALOG.index


# --- Поиск: находит своё, молчит на чужом ---


def test_the_same_material_is_found_by_any_of_its_spellings():
    cement = CATALOG.find("цемент м500")
    assert cement is not None
    for spelling in ("ЦЕМ II 42.5", "цемент пятисотый", "м500 мешок 50 кг", "Цемент М-500"):
        assert CATALOG.find(spelling) is cement, spelling
    assert cement.unit == "т"


def test_a_typo_still_finds_the_item():
    assert CATALOG.find("лианолеум") is CATALOG.find("линолеум")


def test_an_ambiguous_word_returns_nothing_rather_than_a_guess():
    """«Плитка» — это и керамическая, и керамогранит, и тротуарная."""
    assert CATALOG.find("плитка") is None


def test_an_unknown_name_returns_nothing():
    assert CATALOG.find("генератор идей") is None
    assert CATALOG.find("") is None


def test_works_and_materials_are_both_present():
    kinds = {item.kind for item in CATALOG.items}
    assert kinds == KINDS
    assert CATALOG.find("укладка плитки").kind == "work"
    assert CATALOG.find("керамогранит").kind == "material"


def test_work_units_from_the_canon_are_actually_used():
    """Точка и смена появились в каноне ради этого (ADR-016)."""
    assert CATALOG.find("электроточка").unit == "точка"
    assert CATALOG.find("аренда вышки").unit == "смена"


def test_an_item_without_aliases_still_indexes_itself():
    catalog = build([{"name": "Цемент", "unit": "т", "kind": "material", "aliases": []}])
    assert catalog.find("цемент") == Item(name="Цемент", unit="т", kind="material")
