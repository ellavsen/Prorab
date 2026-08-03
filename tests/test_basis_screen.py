"""Единственный экран, где прораб решает про деньги заказчика.

Формулировка здесь важнее кода: «6%» читаются двумя способами, и человек
выбирает не термин, а число. Поэтому проверяется не «текст непустой», а что
именно в нём есть и, главное, чего в нём нет.

Второе, что проверяется, — что вопроса не задают дважды. У прораба почти
всегда тот же договор, и лишний экран на входе бьёт по сценарию «начал смету и
диктуешь».
"""

import os
import pathlib
from decimal import Decimal as D

import pytest

from conftest import async_test, open_storage
from smeta_core import Category, PositionData, RateBase
from smeta_storage import Estimate, positions, send, set_rate_base

UID = 4242


class FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.replies: list[tuple[str, object]] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs.get("reply_markup")))


class FakeUpdate:
    def __init__(self, text: str):
        self.message = FakeMessage(text)
        self.effective_message = self.message
        self.effective_user = type("User", (), {"id": UID})()


@pytest.fixture
def bot(tmp_path, monkeypatch):
    os.environ["ESTIMATE_DB_URL"] = f"sqlite:///{tmp_path / 'basis.db'}"
    _engine, Session = open_storage(tmp_path / "basis.db")

    from bot.handlers import estimates

    monkeypatch.setattr(estimates, "SessionLocal", Session)

    async def command(text: str) -> FakeUpdate:
        update = FakeUpdate(text)
        handler = estimates.cmd_new if text.startswith("/new") else estimates.cmd_basis
        await handler(update, None)
        return update

    return command, Session


def buttons(markup) -> list[str]:
    if markup is None or not hasattr(markup, "inline_keyboard"):
        return []
    return [button.text for row in markup.inline_keyboard for button in row]


# --- Самая первая смета: спрашиваем один раз ---


@async_test
async def test_the_first_estimate_asks_with_money_and_not_with_terms(bot):
    """Числа вместо словаря: «наценку» и «удержание» он читает как синонимы."""
    command, _Session = bot
    update = await command("/new Первая")

    assert len(update.message.replies) == 2, "создание и вопрос — разными сообщениями"
    question, markup = update.message.replies[1]

    assert "1060,00" in question and "1063,83" in question
    assert buttons(markup) == ["к цене: 1060,00 ₽", "от суммы: 1063,83 ₽"]

    assert question.startswith("Один раз спрошу")

    lowered = question.lower()
    for forbidden in ("наценк", "удержан", "маржа", "налог", "рекоменд", "правильн"):
        assert forbidden not in lowered, f"в вопросе слово «{forbidden}»"


@async_test
async def test_the_question_does_not_block_the_work(bot):
    """Смета создана и активна до всякого ответа: вопрос можно не читать."""
    command, Session = bot
    await command("/new Первая")
    with Session() as db:
        from smeta_storage import current_estimate

        assert current_estimate(db, UID).name == "Первая"


@async_test
async def test_the_question_is_asked_only_once(bot):
    """Вторая смета продолжает договор молча — вопроса больше нет."""
    command, _Session = bot
    await command("/new Первая")
    update = await command("/new Вторая")

    line, markup = update.message.replies[1]
    assert line.startswith("Процент:")
    assert "Как в №1" in line
    assert buttons(markup) == ["Поменять процент"]
    assert "1063,83" not in line, "второй раз объяснять не надо"


# --- Наследование ---


@async_test
async def test_the_inherited_line_names_the_base_and_where_it_came_from(bot):
    command, Session = bot
    await command("/new Первая")
    with Session() as db:
        set_rate_base(db, db.get(Estimate, 1), RateBase.PRICE)

    update = await command("/new Вторая")
    assert update.message.replies[1][0] == "Процент: 6,00% от суммы. Как в №1."


@async_test
async def test_different_rates_per_category_stay_readable(bot):
    command, Session = bot
    await command("/new Первая")
    with Session() as db:
        from smeta_storage import set_rates

        set_rates(db, db.get(Estimate, 1), work_bp=1000, material_bp=0)

    update = await command("/new Вторая")
    assert update.message.replies[1][0] == (
        "Процент: работы 10,00%, материалы 0,00% — к цене. Как в №1."
    )


# --- Команда ---


@async_test
async def test_basis_shows_the_effect_and_names_the_other_option(bot):
    command, _Session = bot
    await command("/new Ремонт")
    update = await command("/basis")

    text = update.message.replies[0][0]
    assert "6,00% к цене" in text
    assert "1000,00 ₽ → заказчику 1060,00 ₽" in text
    assert text.endswith("Поменять: /basis от суммы")


@async_test
async def test_basis_takes_the_same_words_that_were_on_the_button(bot):
    command, Session = bot
    await command("/new Ремонт")
    await command("/basis от суммы")

    with Session() as db:
        assert db.get(Estimate, 1).rate_base == RateBase.PRICE


@async_test
async def test_basis_does_not_guess_at_an_unknown_word(bot):
    command, Session = bot
    await command("/new Ремонт")
    update = await command("/basis как-нибудь")

    assert "Не понял" in update.message.replies[0][0]
    with Session() as db:
        assert db.get(Estimate, 1).rate_base == RateBase.COST


@async_test
async def test_basis_on_a_sent_estimate_is_refused_by_the_guard(bot):
    """Оно меняет суммы всех строк, а не подпись под ними."""
    command, Session = bot
    await command("/new Ремонт")
    with Session() as db:
        estimate = db.get(Estimate, 1)
        positions.add(db, UID, estimate.id, PositionData(
            Category.WORK, "Побелка", D("1"), D("1000"), "м²"))
        db.commit()
        send(db, estimate)

    from smeta_storage import FrozenEstimateError

    with pytest.raises(FrozenEstimateError):
        await command("/basis от суммы")


def test_the_example_number_is_computed_and_not_written_down():
    """Число на экране про деньги обязано приходить из калькулятора.

    Литерал разошёлся бы с расчётом однажды и незаметно — и именно там, где
    человек по нему принимает решение о чужих деньгах.
    """
    from bot import texts

    source = pathlib.Path(texts.__file__).read_text(encoding="utf-8")
    assert "1063,83" not in source and "1060,00" not in source
    assert texts.basis_example(RateBase.PRICE) == "1063,83"
    assert texts.basis_example(RateBase.COST) == "1060,00"
