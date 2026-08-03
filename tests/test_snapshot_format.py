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
    SNAPSHOT_FORMAT,
    Category,
    IntegrityError,
    PositionData,
    RateBase,
    calculate_estimate,
    canonical_form,
    frozen_hash,
)
from smeta_core.snapshot import _canonical_v1, _canonical_v2
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

V1_CANONICAL = '{"positions":[{"category":"work","name":"Стяжка пола по маякам","price_kop":70000,"qty_milli":104500,"unit":"м²","unit_spoken":"квадрат"},{"category":"material","name":"Цемент М500","price_kop":34990,"qty_milli":20000,"unit":"шт","unit_spoken":"мешок"},{"category":"work","name":"Штробление под розетку","price_kop":120055,"qty_milli":7125,"unit":"","unit_spoken":""}],"rates":{"material":1250,"work":600}}'
V1_HASH = "b96f077077678d61f07522a532d767cdfdd74ecfb950848594f2d3f082f976eb"

# Формат 2 добавляет основание ставки и пишет его всегда, оба значения.
V2_COST_HASH = "0f3addec6b3f556db7943ae7bb5237d4c3438df6b2f786a0bb3f0089bcfcf93f"
V2_PRICE_HASH = "0af08773ecbda67a9b647b06bd36b977b006b9c3fa0db7e0b74e6fa09020c3ed"

# Суммы — вторая половина контракта: check_integrity сверяет и frozen_total.
COST_TOTALS = (D("88701.92"), D("5776.99"), D("94478.91"))   # subtotal, markup, total
PRICE_TOTALS = (D("88701.92"), D("6214.85"), D("94916.77"))

# Смета без позиций тоже замораживается (money.md B3), и форма блока ставок
# видна в ней в чистом виде.
EMPTY_V1_CANONICAL = '{"positions":[],"rates":{"material":9999,"work":0}}'
EMPTY_V1_HASH = "31d4ddb646f0f8adfc49df3eefc91187bdc1fc5810f586cff85de09ced9ccd9c"


def test_format_one_serializes_exactly_this_string_forever():
    """Строка — диагностика: по её диффу сразу видно, что именно уехало.

    Пришпилена к самому формату 1, а не к «текущему»: когда текущим станет
    следующий номер, этот тест обязан остаться зелёным без правок. В этом и
    смысл версий.
    """
    assert _canonical_v1(RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE, RateBase.COST) == V1_CANONICAL
    assert _canonical_v1([], D("0.00"), D("99.99"), RateBase.COST) == EMPTY_V1_CANONICAL


def test_format_one_hashes_to_exactly_this_value_forever():
    """Хеш — то, что лежит в чужих базах. Он и есть контракт.

    Пришпилен отдельно от строки: кодировка и алгоритм хеширования — тоже
    часть формата, и их подмену сравнение строк не поймает.
    """
    assert frozen_hash(RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE, snapshot_format=1) == V1_HASH
    assert frozen_hash([], D("0.00"), D("99.99"), snapshot_format=1) == EMPTY_V1_HASH


def test_format_one_cannot_represent_a_percent_taken_from_the_sum():
    """Молчаливо посчитать её как обычную наценку было бы хуже отказа."""
    with pytest.raises(ValueError, match="Формат 1"):
        _canonical_v1(RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE, RateBase.PRICE)


def test_format_two_pins_both_bases():
    """Пришпилен до того, как станет текущим: дрейфовать ему уже нельзя."""
    args = (RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE)
    assert frozen_hash(*args, RateBase.COST, snapshot_format=2) == V2_COST_HASH
    assert frozen_hash(*args, RateBase.PRICE, snapshot_format=2) == V2_PRICE_HASH
    assert '"rate_base":"price"' in _canonical_v2(*args, RateBase.PRICE)


def test_an_unknown_format_refuses_instead_of_guessing():
    """Смета из будущего — не повод выдать документ по сегодняшнему алгоритму."""
    with pytest.raises(ValueError, match="формат"):
        frozen_hash(RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE, snapshot_format=99)


def test_the_frozen_totals_are_exactly_these_numbers():
    """Правка округления или множителя ломает отправленные сметы, не тронув хеш."""
    cost = calculate_estimate(RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE)
    price = calculate_estimate(RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE, RateBase.PRICE)
    assert (cost.subtotal, cost.markup, cost.total) == COST_TOTALS
    assert (price.subtotal, price.markup, price.total) == PRICE_TOTALS


def test_the_current_format_is_what_freezing_uses_without_being_asked():
    """Заморозить старым форматом случайно нельзя: параметр по умолчанию — текущий."""
    args = (RICH, RICH_WORK_RATE, RICH_MATERIAL_RATE)
    assert canonical_form(*args) == canonical_form(*args, snapshot_format=SNAPSHOT_FORMAT)


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
        "smeta_core.snapshot.canonical_form",
        lambda *args, **kwargs: canonical_form(*args, **kwargs) + '"новое поле"',
    )
    with pytest.raises(IntegrityError):
        verified_totals(db, estimate)


def test_changing_the_arithmetic_takes_them_away_too_without_touching_the_hash(db, monkeypatch):
    """Слепок сошёлся, итог — нет. Именно этот путь версия сериализации не ловит."""
    estimate = sent_estimate(db)

    monkeypatch.setattr(
        "smeta_core.freeze.calculate_estimate",
        lambda rows, work, material, base: calculate_estimate(rows, work + D("1.00"), material),
    )
    with pytest.raises(IntegrityError):
        verified_totals(db, estimate)
