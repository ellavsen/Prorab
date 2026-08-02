"""Подсказка цены в предпросмотре (ADR-017).

Главное свойство то же, что у всего предпросмотра: ничего не подставляется
молча. Подсказка — предложение, строка без цены остаётся негодной, и цена
появляется в ней ровно по нажатию.
"""

from decimal import Decimal as D

import pytest
from test_preview import UID, FakeMessage, FakeQuery, bot, candidates  # noqa: F401

from conftest import async_test
from smeta_ai import (
    Extraction,
    ExtractionStatus,
    FieldStatus,
    PositionCandidate,
    Price,
    PriceScope,
    Quantity,
)
from smeta_core import Category, PositionData
from smeta_storage import RETENTION_LIMIT, create_estimate, pending, positions


def priceless(name="Цемент М500", unit="", unit_spoken="мешков"):
    """Позиция, у которой названо всё, кроме цены."""
    return Extraction(status=ExtractionStatus.OK, positions=(
        PositionCandidate(
            name=name,
            qty=Quantity(status=FieldStatus.STATED, value="20"),
            price=Price(status=FieldStatus.MISSING, scope=PriceScope.UNKNOWN, value=""),
            unit=unit, unit_spoken=unit_spoken, category="material",
            source_quote=name,
        ),
    ))


def bought(db, uid, price, name="Цемент М500", unit="", unit_spoken="мешков"):
    """Человек когда-то сам ввёл эту цену — в своей же смете."""
    estimate = create_estimate(db, uid, name="Прошлая")
    positions.add(db, uid, estimate.id, PositionData(
        category=Category.MATERIAL, name=name, qty=D("20"), price=D(price),
        unit=unit, unit_spoken=unit_spoken,
    ))
    db.commit()


@async_test
async def test_a_price_you_paid_before_is_offered_but_not_filled_in(bot):  # noqa: F811
    """Ничего не подставляется молча — ни моделью, ни историей (ADR-012)."""
    _ai, preview, _positions, Session, estimate_id = bot
    message = FakeMessage()
    with Session() as db:
        bought(db, UID, "380")
        await preview.offer(message, db, UID, priceless())

        row = pending.load(db, UID)[0]
        assert row.price == "", "цена не имеет права появиться сама"
        assert row.problem, "строка без цены остаётся негодной"
        assert row.hint_price == "380.00"

    assert "вы брали по 380,00" in message.last
    assert "мешков" in message.last
    assert positions.load(db, UID, estimate_id) == []


@async_test
async def test_the_button_is_what_puts_the_price_in(bot):  # noqa: F811
    _ai, preview, _positions, Session, _estimate_id = bot
    with Session() as db:
        bought(db, UID, "380")
        await preview.offer(FakeMessage(), db, UID, priceless())

        query = FakeQuery()
        await preview.handle_action(query, db, UID, "hint:1")

        row = pending.load(db, UID)[0]
        assert row.price == "380.00"
        assert row.problem is None
    # 20 × 380 = 7600, с наценкой материалов 6% — 8056,00. Считает домен.
    assert "20 мешков × 380,00 = <b>8056,00</b>" in query.last


@async_test
async def test_the_median_button_appears_only_from_three_purchases(bot):  # noqa: F811
    _ai, preview, _positions, Session, _estimate_id = bot
    with Session() as db:
        bought(db, UID, "350")
        bought(db, UID, "380")
        await preview.offer(FakeMessage(), db, UID, priceless())
        assert pending.load(db, UID)[0].hint_median is None

        bought(db, UID, "370")
        message = FakeMessage()
        await preview.offer(message, db, UID, priceless())
        assert pending.load(db, UID)[0].hint_median == "370.00"
    assert "чаще всего 370,00" in message.last


@async_test
async def test_a_price_per_another_unit_is_never_offered(bot):  # noqa: F811
    """«350 за мешок» и «350 за кг» — разные величины (ADR-015)."""
    _ai, preview, _positions, Session, _estimate_id = bot
    with Session() as db:
        bought(db, UID, "380", unit="кг", unit_spoken="")
        message = FakeMessage()
        await preview.offer(message, db, UID, priceless(unit="", unit_spoken="мешков"))

        assert pending.load(db, UID)[0].hint_price is None
    assert "вы брали" not in message.last


@async_test
async def test_nothing_is_offered_when_there_is_no_history(bot):  # noqa: F811
    """Своих цен нет — подсказки нет. «Нет данных» на пустом месте не пишем."""
    _ai, preview, _positions, Session, _estimate_id = bot
    with Session() as db:
        message = FakeMessage()
        await preview.offer(message, db, UID, priceless())

        assert pending.load(db, UID)[0].hint_price is None
    assert "💡" not in message.last


@async_test
async def test_a_row_without_quantity_gets_no_hint(bot):  # noqa: F811
    """Цена не спасёт строку, которой не хватает и количества (E21 из eval)."""
    _ai, preview, _positions, Session, _estimate_id = bot
    nothing = Extraction(status=ExtractionStatus.OK, positions=(
        PositionCandidate(
            name="Цемент М500",
            qty=Quantity(status=FieldStatus.MISSING, value=""),
            price=Price(status=FieldStatus.MISSING, scope=PriceScope.UNKNOWN, value=""),
            unit_spoken="мешков", category="material", source_quote="цемент",
        ),
    ))
    with Session() as db:
        bought(db, UID, "380")
        message = FakeMessage()
        await preview.offer(message, db, UID, nothing)

        assert pending.load(db, UID)[0].hint_price is None
    assert "💡" not in message.last


@async_test
async def test_the_hint_survives_the_estimate_that_taught_it(bot):  # noqa: F811
    """Смета вытеснена ретеншеном — цена из неё всё ещё подсказывается."""
    _ai, preview, _positions, Session, _estimate_id = bot
    with Session() as db:
        from smeta_storage import enforce_retention

        bought(db, UID, "380")
        for _ in range(RETENTION_LIMIT + 1):
            create_estimate(db, UID, name="Новая")
        db.commit()
        enforce_retention(db, UID)

        message = FakeMessage()
        await preview.offer(message, db, UID, priceless())
        assert pending.load(db, UID)[0].hint_price == "380.00"
    assert "вы брали по 380,00" in message.last


def test_the_russian_plural_of_times_is_not_a_placeholder():
    from bot.texts import _times

    assert (_times(1), _times(2), _times(4), _times(5)) == ("1 раз", "2 раза", "4 раза", "5 раз")
    assert (_times(11), _times(21), _times(22)) == ("11 раз", "21 раз", "22 раза")


@pytest.mark.parametrize("median", [False, True])
def test_applying_a_hint_that_does_not_exist_changes_nothing(bot, median):  # noqa: F811
    _ai, _preview, _positions, Session, _estimate_id = bot
    from bot.handlers import hints

    with Session() as db:
        assert hints.apply(db, UID, ordinal=1, median=median) is False
