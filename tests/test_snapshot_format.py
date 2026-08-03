"""Ремень безопасности слепка: эти значения не имеют права измениться молча.

`check_integrity` пересчитывает хеш отправленной сметы **текущим кодом** и
сверяет с записанным при заморозке. Поэтому любая правка `canonical_form` или
денежной арифметики обнуляет разом все уже отправленные документы: PDF и XLSX
перестают выдаваться, а публичная страница отвечает заказчику нейтральным 404
и по ADR-020 §3 не имеет права назвать причину. Отказ выходит тихим, полным и
неотличимым от «ссылка истекла».

До этого файла ни одной проверки на **конкретное** значение слепка в проекте не
было: все они относительные (хеш A ≠ хеш B), и такую правку можно было внести,
глядя на зелёные тесты.

Если тест ниже упал — константы править нельзя. Падение означает не «эталон
устарел», а «у всех, кто уже отправил смету, документы больше не выдаются».
Правильный ответ — версия формата рядом с хешем: старая версия остаётся в коде
и продолжает сверять то, что заморожено ею.
"""

from decimal import Decimal as D

import pytest

from conftest import open_storage
from smeta_core import (
    Category,
    IntegrityError,
    PositionData,
    calculate_estimate,
    canonical_form,
    frozen_hash,
)
from smeta_storage import create_estimate, positions, send, set_rates, verified_totals

UID = 42

# Позиции подобраны так, чтобы задеть каждое поле сериализации: обе категории,
# кириллица, канон и сказанное слово по отдельности, пустые единицы, дробное
# количество и цена с копейками. Две ставки РАЗНЫЕ — иначе их перестановка
# местами не изменила бы ни строку, ни хеш, и тест не заметил бы подмены.
RICH = (
    PositionData(Category.WORK, "Стяжка пола по маякам", D("104.5"), D("700.00"),
                 unit="м²", unit_spoken="квадрат"),
    PositionData(Category.MATERIAL, "Цемент М500", D("20"), D("349.90"),
                 unit="шт", unit_spoken="мешок"),
    PositionData(Category.WORK, "Штробление под розетку", D("7.125"), D("1200.55")),
)
RICH_WORK_RATE = D("6.00")
RICH_MATERIAL_RATE = D("12.50")

RICH_CANONICAL = '{"positions":[{"category":"work","name":"Стяжка пола по маякам","price_kop":70000,"qty_milli":104500,"unit":"м²","unit_spoken":"квадрат"},{"category":"material","name":"Цемент М500","price_kop":34990,"qty_milli":20000,"unit":"шт","unit_spoken":"мешок"},{"category":"work","name":"Штробление под розетку","price_kop":120055,"qty_milli":7125,"unit":"","unit_spoken":""}],"rates":{"material":1250,"work":600}}'
RICH_HASH = "b96f077077678d61f07522a532d767cdfdd74ecfb950848594f2d3f082f976eb"
RICH_TOTALS = (D("88701.92"), D("5776.99"), D("94478.91"))  # subtotal, markup, total

# Смета без позиций тоже замораживается (money.md B3), и форма блока ставок
# видна в ней в чистом виде.
EMPTY_CANONICAL = '{"positions":[],"rates":{"material":9999,"work":0}}'
EMPTY_HASH = "31d4ddb646f0f8adfc49df3eefc91187bdc1fc5810f586cff85de09ced9ccd9c"


def test_the_canonical_form_is_exactly_this_string():
    """Строка — диагностика: по её диффу сразу видно, что именно уехало."""
    assert canonical_form(RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE) == RICH_CANONICAL
    assert canonical_form([], D("0.00"), D("99.99")) == EMPTY_CANONICAL


def test_the_frozen_hash_is_exactly_this_value():
    """Хеш — то, что лежит в чужих базах. Он и есть контракт.

    Пришпилен отдельно от строки: кодировка и алгоритм хеширования — тоже
    часть формата, и их подмену сравнение строк не поймает.
    """
    assert frozen_hash(RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE) == RICH_HASH
    assert frozen_hash([], D("0.00"), D("99.99")) == EMPTY_HASH


def test_the_frozen_totals_are_exactly_these_numbers():
    """Вторая половина контракта заморозки — не хеш, а сами суммы.

    `check_integrity` сверяет и `frozen_total`, поэтому правка округления или
    множителя ломает отправленные сметы, не тронув хеш вовсе. Версия формата
    обязана покрывать арифметику, а не только сериализацию.
    """
    totals = calculate_estimate(RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE)
    assert (totals.subtotal, totals.markup, totals.total) == RICH_TOTALS


@pytest.fixture
def db(tmp_path):
    _engine, Session = open_storage(tmp_path / "snapshot.db")
    with Session() as session:
        yield session


def sent_estimate(db):
    estimate = create_estimate(db, UID, name="Смета")
    set_rates(db, estimate, work_bp=600, material_bp=1250)
    for item in RICH:
        positions.add(db, UID, estimate.id, item)
    db.commit()
    return send(db, estimate)


def test_changing_the_serialization_takes_documents_away_from_the_customer(db, monkeypatch):
    """Показывает последствие, ради которого написан весь файл.

    Смета отправлена, ничего в ней не менялось — но алгоритм слепка поехал, и
    заказчик со ссылкой видит ту же страницу, что при отозванной ссылке.
    """
    estimate = sent_estimate(db)
    assert verified_totals(db, estimate).total == estimate.frozen_total

    monkeypatch.setattr(
        "smeta_core.freeze.canonical_form",
        lambda rows, work, material: canonical_form(rows, work, material) + '"новое поле"',
    )
    with pytest.raises(IntegrityError):
        verified_totals(db, estimate)


def test_changing_the_arithmetic_takes_them_away_too_without_touching_the_hash(db, monkeypatch):
    """Слепок сошёлся, итог — нет. Именно этот путь версия сериализации не ловит."""
    estimate = sent_estimate(db)

    monkeypatch.setattr(
        "smeta_core.freeze.calculate_estimate",
        lambda rows, work, material: calculate_estimate(rows, work + D("1.00"), material),
    )
    with pytest.raises(IntegrityError):
        verified_totals(db, estimate)
