"""Публичная страница: те же числа, ничего лишнего, ничего извне.

Страница — четвёртая поверхность после бота, XLSX и PDF, и первая, которую
видит посторонний. Поэтому проверяется не только «отрисовалось», а два
отдельных свойства: суммы совпадают с доменом до копейки и страница не ходит
никуда наружу — адрес с токеном не должен уехать в чужой Referer.
"""

import re
from datetime import date
from decimal import Decimal as D

import pytest

from smeta_core import Category, PositionData, calculate_estimate, format_money
from smeta_export import DocumentMeta, build_page, unavailable_page
from smeta_export.page import FONT_STACK

RATE = D("6.00")
TODAY = date(2026, 8, 3)

# Всё, чем страница могла бы попроситься наружу. Любое совпадение — утечка
# адреса в Referer чужого сервера (ADR-020).
OUTSIDE = re.compile(
    r"https?:|//[a-z]|@import|@font-face|<script|<img|<iframe|<link|url\(", re.I
)


def meta(**kwargs) -> DocumentMeta:
    base = dict(number=3, version=2, title="Ремонт на объекте", on=TODAY,
                work_rate=RATE, material_rate=RATE, status="Отправлена заказчику")
    return DocumentMeta(**{**base, **kwargs})


def rows():
    return [
        PositionData(Category.WORK, "Побелка потолка", D("150"), D("3000"), unit="м²"),
        PositionData(Category.WORK, "Стяжка", D("40.5"), D("700"), unit="м²"),
        PositionData(Category.MATERIAL, "Цемент М500", D("20"), D("380"),
                     unit="", unit_spoken="мешков"),
    ]


def rendered(positions=None, **kwargs):
    positions = rows() if positions is None else positions
    totals = calculate_estimate(positions, RATE, RATE)
    return totals, build_page(totals, meta(), **kwargs)


# --- Числа ---


def test_every_number_on_the_page_comes_from_the_domain():
    totals, page = rendered()
    for line in totals.lines:
        assert format_money(line.total) in page, line.position.name
        assert format_money(line.position.price) in page
    assert format_money(totals.total) in page
    assert format_money(totals.markup) in page
    assert format_money(totals.subtotal) in page


def test_money_is_formatted_the_one_way_the_project_formats_money():
    _totals, page = rendered()
    assert "477000,00" in page
    assert "477000.00" not in page


def test_the_unit_is_printed_in_its_dictionary_form():
    """«мешков» сказано, «мешок» напечатано — та же приведённая форма, что в PDF."""
    _totals, page = rendered()
    assert "мешок" in page
    assert "мешков" not in page


def test_an_empty_section_is_not_printed():
    only_work = [PositionData(Category.WORK, "Побелка", D("1"), D("100"))]
    _totals, page = rendered(only_work)
    assert "Работы" in page
    assert "Материалы" not in page


# --- Ничего извне ---


def test_the_page_asks_the_network_for_nothing():
    """Единственная настоящая защита адреса: страница никуда не ходит."""
    _totals, page = rendered(approve_url="/e/abc/approve")
    leaked = OUTSIDE.findall(page)
    assert not leaked, f"страница тянет внешнее: {leaked}"


def test_the_font_is_the_one_the_reader_already_has():
    """@font-face с CDN унёс бы токен в Referer — поэтому системный стек."""
    _totals, page = rendered()
    assert FONT_STACK in page
    assert "@font-face" not in page


def test_the_two_tables_line_up():
    """Найдено рендером: колонки двух таблиц разъезжались друг с другом.

    Разметка была корректной, и все тесты — зелёными: браузер сам подбирал
    ширины по содержимому, и у двух таблиц они выходили разными. В PDF ширины
    заданы жёстко (COLUMN_WIDTHS), документ должен быть один.
    """
    _totals, page = rendered()
    assert "table-layout: fixed" in page
    assert page.count("<table>") == 2


def test_the_page_carries_no_commentary_for_the_customer():
    """Комментарий в CSS — это вес в каждой выдаче и наш русский текст у чужого.

    Заодно ловушка: первая версия объясняла вёрстку прямо в стилях, и слово
    «Материалы» из комментария попадало в смету, где раздела «Материалы» нет.
    """
    _totals, page = rendered()
    assert "/*" not in page
    assert "<!--" not in page


def test_the_page_is_one_file_with_nothing_to_fetch():
    _totals, page = rendered()
    assert page.startswith("<!doctype html>")
    assert "<style>" in page, "стили встроены, а не подключены"


# --- Что человек написал сам ---


@pytest.mark.parametrize("name", [
    "<script>alert(1)</script>",
    'Плитка "Керама" 30x30 & сопутствующее',
    "Стяжка'; DROP TABLE positions; --",
])
def test_what_the_human_typed_is_escaped(name):
    """Наименование пишет человек, а читает его браузер постороннего."""
    _totals, page = rendered([PositionData(Category.WORK, name, D("1"), D("100"))])
    assert "<script>" not in page
    assert name not in page, "сырой текст не должен попадать в разметку"
    assert "&lt;" in page or "&amp;" in page or "&#x27;" in page


def test_the_title_is_escaped_too():
    totals = calculate_estimate(rows(), RATE, RATE)
    page = build_page(totals, meta(title="<b>Иванов</b>"))
    assert "<b>Иванов</b>" not in page
    assert "&lt;b&gt;Иванов&lt;/b&gt;" in page


# --- Согласование ---


def test_the_button_appears_only_while_there_is_something_to_approve():
    _totals, plain = rendered()
    assert "<form" not in plain

    _totals, offered = rendered(approve_url="/e/abc/approve")
    assert '<form method="post" action="/e/abc/approve">' in offered
    assert "Согласовать смету" in offered


def test_an_approved_estimate_shows_the_date_instead_of_the_button():
    _totals, page = rendered(
        approve_url="/e/abc/approve", approved_on=date(2026, 8, 3)
    )
    assert "Согласовано 3 августа 2026" in page
    assert "<form" not in page, "согласовать дважды нечего"


# --- Страница отказа ---


def test_the_unavailable_page_names_no_reason():
    """«Нет», «отозвано», «истекло» и «не сошлось» выглядят одинаково."""
    page = unavailable_page()
    assert "Ссылка недоступна" in page
    assert "Запросите новую у отправителя" in page
    for word in ("отозв", "истек", "просроч", "удал", "не найден", "целостн"):
        assert word not in page.lower(), word


def test_the_unavailable_page_carries_no_data():
    page = unavailable_page()
    assert "Смета" not in page
    assert not OUTSIDE.findall(page)
