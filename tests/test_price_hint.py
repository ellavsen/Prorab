"""Подсказка цены в предпросмотре (ADR-017).

Главное свойство то же, что у всего предпросмотра: ничего не подставляется
молча. Подсказка — предложение, строка без цены остаётся негодной, и цена
появляется в ней ровно по нажатию.
"""

from dataclasses import replace
from datetime import timedelta
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
from smeta_storage import RETENTION_LIMIT, create_estimate, pending, positions, utcnow


def priceless(name="Цемент М500", unit="", unit_spoken="мешков", category="material"):
    """Позиция, у которой названо всё, кроме цены."""
    return Extraction(status=ExtractionStatus.OK, positions=(
        PositionCandidate(
            name=name,
            qty=Quantity(status=FieldStatus.STATED, value="20"),
            price=Price(status=FieldStatus.MISSING, scope=PriceScope.UNKNOWN, value=""),
            unit=unit, unit_spoken=unit_spoken, category=category,
            source_quote=name,
        ),
    ))


def bought(db, uid, price, name="Цемент М500", unit="", unit_spoken="мешков",
           days_ago=0, category=Category.MATERIAL, performer=""):
    """Человек когда-то сам ввёл эту цену — в своей же смете.

    days_ago двигает дату покупки: у цен, названных в разные дни, «последняя»
    определена однозначно, а у названных в один день — нет (см. известные
    пробелы). Тесты про разброс не должны зависеть от этой неопределённости.
    """
    estimate = create_estimate(db, uid, name="Прошлая")
    row = positions.add(db, uid, estimate.id, PositionData(
        category=category, name=name, qty=D("20"), price=D(price),
        unit=unit, unit_spoken=unit_spoken,
    ), performer=performer)
    if days_ago:
        # Значение по умолчанию проставляется только при flush, поэтому дата
        # задаётся целиком, а не сдвигается.
        row.created_at = utcnow() - timedelta(days=days_ago)
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

    # «₽/мешок», а не «₽/мешков»: здесь единица стоит сама по себе, в позиции
    # «за одну», и родительный падеж — обрывок фразы, а не единица.
    assert "вы брали по 380,00 ₽/мешок —" in message.last
    assert "мешков" not in message.last
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
async def test_prices_that_disagree_are_shown_as_a_range(bot):  # noqa: F811
    """Последняя цена — не «сколько это стоит», когда цены разошлись (ADR-026)."""
    _ai, preview, _positions, Session, _estimate_id = bot
    message = FakeMessage()
    with Session() as db:
        for price, days_ago in (("450", 40), ("700", 20), ("1100", 0)):
            bought(db, UID, price, days_ago=days_ago)
        await preview.offer(message, db, UID, priceless())

        row = pending.load(db, UID)[0]
        assert (row.hint_low, row.hint_high) == ("450.00", "1100.00")

    assert "вы платили от 450,00 до 1100,00 ₽/мешок" in message.last
    # Последняя не пропадает: кнопка предлагает именно её, и она подписана.
    assert "последняя 1100,00" in message.last
    assert "чаще всего 700,00" in message.last


@async_test
async def test_prices_from_one_day_offer_no_last_at_all(bot):  # noqa: F811
    """Времени точнее дня в истории нет — значит, «последняя» неизвестна.

    Молчание вместо неверного факта, и молчание полное: вместе со словом
    гаснет кнопка, иначе утверждение ушло бы с экрана, оставшись в поведении
    (ADR-026).
    """
    _ai, preview, _positions, Session, _estimate_id = bot
    from bot.handlers import hints

    message = FakeMessage()
    with Session() as db:
        for price in ("450", "1100"):
            bought(db, UID, price)          # обе — сегодня
        await preview.offer(message, db, UID, priceless())

        row = pending.load(db, UID)[0]
        assert row.hint_price is None, "последняя не определена"
        assert (row.hint_low, row.hint_high) == ("450.00", "1100.00")
        # Кнопка берётся из того же поля, поэтому её нет...
        assert hints.hinted_ordinals(pending.load(db, UID)) == []
        # ...и нажать её в обход тоже нельзя.
        assert hints.apply(db, UID, ordinal=1) is False
        assert pending.load(db, UID)[0].price == ""

    assert "вы платили от 450,00 до 1100,00 ₽/мешок" in message.last
    assert "последняя не определена: цены названы в один день" in message.last


@async_test
async def test_one_day_is_unambiguous_when_the_prices_agree(bot):  # noqa: F811
    """Несколько одинаковых цен одного дня — «последняя» определена.

    Какую из них ни возьми, число то же самое, и молчать не о чем.
    """
    _ai, preview, _positions, Session, _estimate_id = bot
    with Session() as db:
        bought(db, UID, "450", days_ago=30)
        for _ in range(2):
            bought(db, UID, "1100")         # обе — сегодня, но равны
        await preview.offer(FakeMessage(), db, UID, priceless())

        row = pending.load(db, UID)[0]
        assert row.hint_price == "1100.00"


@async_test
async def test_one_price_repeated_is_not_a_range(bot):  # noqa: F811
    """Разброс показывается, когда он есть. «От 380 до 380» — шум."""
    _ai, preview, _positions, Session, _estimate_id = bot
    message = FakeMessage()
    with Session() as db:
        for _ in range(3):
            bought(db, UID, "380")
        await preview.offer(message, db, UID, priceless())

        row = pending.load(db, UID)[0]
        assert row.hint_low == row.hint_high == "380.00"

    assert "вы брали по 380,00 ₽/мешок —" in message.last
    assert "вы платили от" not in message.last


@async_test
async def test_a_typo_finds_your_own_history_and_says_so(bot):  # noqa: F811
    """«Грутновка» находит свою же историю — но не молча (ADR-027)."""
    _ai, preview, _positions, Session, _estimate_id = bot
    message = FakeMessage()
    with Session() as db:
        bought(db, UID, "380", name="Грунтовка")
        await preview.offer(message, db, UID, priceless(name="Грутновка"))

        row = pending.load(db, UID)[0]
        assert row.hint_price == "380.00"
        assert row.hint_matched_name == "грунтовка"

    assert "«грунтовка»: вы брали по 380,00" in message.last


@async_test
async def test_the_matched_name_is_silent_when_it_is_the_same(bot):  # noqa: F811
    """Совпало — говорить не о чем, и лишнего слова в подсказке не будет."""
    _ai, preview, _positions, Session, _estimate_id = bot
    message = FakeMessage()
    with Session() as db:
        bought(db, UID, "380")
        await preview.offer(message, db, UID, priceless())

        assert pending.load(db, UID)[0].hint_matched_name is None
    assert "»: вы брали" not in message.last


@async_test
async def test_a_grade_never_borrows_the_price_of_another_grade(bot):  # noqa: F811
    """М400 и М500 — опечатка друг друга по расстоянию и разные деньги по сути."""
    _ai, preview, _positions, Session, _estimate_id = bot
    message = FakeMessage()
    with Session() as db:
        bought(db, UID, "380", name="Цемент М500")
        await preview.offer(message, db, UID, priceless(name="Цемент М400"))

        assert pending.load(db, UID)[0].hint_price is None
    assert "💡" not in message.last


@async_test
async def test_a_work_price_never_answers_for_a_material(bot):  # noqa: F811
    """«ГКЛ» и «ГКЛ монтаж» вложены друг в друга, а цена разная в разы.

    Отличить их есть чем только с тех пор, как история помнит категорию
    (ADR-027, ADR-028): второй проход не выходит за её пределы.
    """
    _ai, preview, _positions, Session, _estimate_id = bot
    message = FakeMessage()
    with Session() as db:
        bought(db, UID, "500", name="ГКЛ монтаж", category=Category.WORK)
        await preview.offer(message, db, UID, priceless(name="ГКЛ"))

        assert pending.load(db, UID)[0].hint_price is None
    assert "💡" not in message.last


@async_test
async def test_a_missing_word_is_forgiven_inside_one_category(bot):  # noqa: F811
    """«Стяжка» находит «Стяжку пола» — обе работы, спорить не о чем."""
    _ai, preview, _positions, Session, _estimate_id = bot
    message = FakeMessage()
    with Session() as db:
        bought(db, UID, "800", name="Стяжка пола", unit_spoken="квадратов",
               category=Category.WORK)
        await preview.offer(
            message, db, UID,
            priceless(name="Стяжка", unit_spoken="квадратов", category="work"),
        )

        row = pending.load(db, UID)[0]
        assert row.hint_price == "800.00"
        assert row.hint_matched_name == "пола стяжка"


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


@async_test
async def test_the_quantity_phrase_keeps_the_case_it_was_said_in(bot):  # noqa: F811
    """«20 мешков» словарной формой ломать нельзя — «20 мешок» не по-русски.

    Тот же unit_spoken, но позиция во фразе другая: здесь он согласован с
    количеством, а в подсказке цены стоит сам по себе.
    """
    _ai, preview, _positions, Session, _estimate_id = bot
    priced = replace(
        priceless().positions[0],
        price=Price(status=FieldStatus.STATED, scope=PriceScope.PER_UNIT, value="380"),
    )
    message = FakeMessage()
    with Session() as db:
        await preview.offer(
            message, db, UID,
            Extraction(status=ExtractionStatus.OK, positions=(priced,)),
        )
    assert "20 мешков × 380,00" in message.last


def test_the_dictionary_form_is_used_only_where_the_unit_stands_alone():
    from smeta_prices import display_unit

    assert display_unit("", "мешков") == "мешок"
    assert display_unit("шт", "мешков") == "мешок"      # канон не подменяет сказанное
    assert display_unit("м²", "") == "м²"
    assert display_unit("", "бухточек") == "бухточек"   # вне словаря — как сказано
    assert display_unit("", "") == ""


def test_the_russian_plural_of_times_is_not_a_placeholder():
    from bot.preview_texts import _times

    assert (_times(1), _times(2), _times(4), _times(5)) == ("1 раз", "2 раза", "4 раза", "5 раз")
    assert (_times(11), _times(21), _times(22)) == ("11 раз", "21 раз", "22 раза")


@pytest.mark.parametrize("median", [False, True])
def test_applying_a_hint_that_does_not_exist_changes_nothing(bot, median):  # noqa: F811
    _ai, _preview, _positions, Session, _estimate_id = bot
    from bot.handlers import hints

    with Session() as db:
        assert hints.apply(db, UID, ordinal=1, median=median) is False
