"""Пошаговый ввод (ADR-010) и выбор прочтения неоднозначной строки (ADR-011).

Хендлеры принимают message/query, а не Update, поэтому проверяются напрямую
простыми заглушками — без поднятия Telegram.
"""

from decimal import Decimal as D

import pytest

from conftest import async_test, open_storage
from smeta_core import AmbiguousLine, Category, parse_position_line
from smeta_storage import create_estimate, positions, set_category, set_current_estimate, user_state

UID = 42


class FakeMessage:
    """Собирает то, что бот сказал пользователю."""

    def __init__(self):
        self.sent: list[str] = []
        self.keyboards: list[object] = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(text)
        self.keyboards.append(kwargs.get("reply_markup"))
        return self

    @property
    def last(self) -> str:
        return self.sent[-1]


class FakeQuery:
    def __init__(self):
        self.message = FakeMessage()
        self.edited: list[str] = []

    async def edit_message_text(self, text, **_kwargs):
        self.edited.append(text)

    @property
    def last(self) -> str:
        return self.edited[-1]


@pytest.fixture
def bot(tmp_path):
    """Хендлеры импортируются лениво: им нужен модуль базы с готовым окружением."""
    import os

    os.environ["ESTIMATE_DB_URL"] = f"sqlite:///{tmp_path / 'step.db'}"
    _engine, Session = open_storage(tmp_path / "step.db")

    from bot.handlers import stepwise

    with Session() as db:
        estimate = create_estimate(db, UID, name="Смета")
        set_current_estimate(db, UID, estimate.id)
        set_category(db, UID, "work")
    return stepwise, Session, estimate.id


async def run_steps(stepwise, db, message, *texts):
    for text in texts:
        await stepwise.handle_text_step(message, db, UID, Category.WORK, text)


@async_test
async def test_full_stepwise_flow_adds_one_position(bot):
    stepwise, Session, estimate_id = bot
    message, query = FakeMessage(), FakeQuery()

    with Session() as db:
        await stepwise.start_draft(message, db, UID)
        assert user_state(db, UID).draft_step == "name"

        await run_steps(stepwise, db, message, "Побелка", "150")
        assert user_state(db, UID).draft_step == "unit"

        await stepwise.handle_unit_choice(query, db, UID, "м²")
        assert user_state(db, UID).draft_step == "price"

        await run_steps(stepwise, db, message, "3000")
        state = user_state(db, UID)
        assert state.draft_step == "confirm"
        # Предпросмотр показывает сумму до того, как что-то попало в смету.
        assert "477 000" in message.last.replace("\xa0", " ") or "477000,00" in message.last
        assert positions.load(db, UID, estimate_id) == []

        await stepwise.handle_draft_action(query, db, UID, "add")
        rows = positions.load(db, UID, estimate_id)

    assert len(rows) == 1
    assert (rows[0].name, rows[0].qty, rows[0].unit, rows[0].price) == (
        "Побелка", D("150"), "м²", D("3000.00"),
    )


@async_test
async def test_draft_survives_a_restart(bot):
    """Главное свойство ADR-010: рестарт не стоит пользователю набранного."""
    stepwise, Session, _ = bot
    message = FakeMessage()

    with Session() as db:
        await stepwise.start_draft(message, db, UID)
        await run_steps(stepwise, db, message, "Стяжка", "40.5")

    # Новая сессия — как будто процесс подняли заново.
    with Session() as db:
        state = user_state(db, UID)
        assert state.draft_step == "unit"
        assert state.draft_name == "Стяжка"
        assert state.draft_qty == D("40.5")


@async_test
async def test_quantity_with_a_unit_skips_the_unit_step(bot):
    stepwise, Session, _ = bot
    message = FakeMessage()
    with Session() as db:
        await stepwise.start_draft(message, db, UID)
        await run_steps(stepwise, db, message, "Побелка", "150 м2")
        state = user_state(db, UID)

    assert state.draft_step == "price"
    assert state.draft_unit == "м²"


@async_test
async def test_skipping_the_unit_fills_it_by_category_and_says_so(bot):
    stepwise, Session, _ = bot
    message, query = FakeMessage(), FakeQuery()
    with Session() as db:
        await stepwise.start_draft(message, db, UID)
        await run_steps(stepwise, db, message, "Побелка", "150")
        await stepwise.handle_unit_choice(query, db, UID, "-")
        state = user_state(db, UID)

    assert state.draft_unit == "м²"          # категория «Работа»
    assert "подставлена" in query.last


@async_test
async def test_bad_quantity_keeps_the_step_and_explains(bot):
    stepwise, Session, _ = bot
    message = FakeMessage()
    with Session() as db:
        await stepwise.start_draft(message, db, UID)
        await run_steps(stepwise, db, message, "Побелка", "0")
        state = user_state(db, UID)

    assert state.draft_step == "qty"          # шаг не сдвинулся
    assert "больше нуля" in message.last


@async_test
async def test_cancel_clears_the_draft(bot):
    stepwise, Session, estimate_id = bot
    message, query = FakeMessage(), FakeQuery()
    with Session() as db:
        await stepwise.start_draft(message, db, UID)
        await run_steps(stepwise, db, message, "Побелка", "150")
        await stepwise.handle_draft_action(query, db, UID, "cancel")
        state = user_state(db, UID)

        assert state.draft_step is None
        assert state.draft_name is None
        assert positions.load(db, UID, estimate_id) == []


@async_test
async def test_restart_starts_a_new_draft_without_adding(bot):
    stepwise, Session, estimate_id = bot
    message, query = FakeMessage(), FakeQuery()
    with Session() as db:
        await stepwise.start_draft(message, db, UID)
        await run_steps(stepwise, db, message, "Побелка", "150")
        await stepwise.handle_draft_action(query, db, UID, "restart")
        state = user_state(db, UID)

        assert state.draft_step == "name"
        assert state.draft_name is None
        assert positions.load(db, UID, estimate_id) == []


@async_test
async def test_ambiguous_line_is_offered_not_guessed(bot):
    stepwise, Session, estimate_id = bot
    message, query = FakeMessage(), FakeQuery()

    with pytest.raises(AmbiguousLine) as caught:
        parse_position_line("Побелка, 150,5, 3000", Category.WORK)

    with Session() as db:
        await stepwise.offer_readings(message, db, UID, caught.value)
        state = user_state(db, UID)
        assert state.draft_step == "ambiguous"
        assert state.pending_line == "Побелка, 150,5, 3000"
        assert "Вариант 1" in message.last

        await stepwise.handle_reading_choice(query, db, UID, "merged")
        rows = positions.load(db, UID, estimate_id)

    assert len(rows) == 1
    assert rows[0].qty == D("150.5")
    assert rows[0].name == "Побелка"


@async_test
async def test_choosing_the_other_reading(bot):
    stepwise, Session, estimate_id = bot
    message, query = FakeMessage(), FakeQuery()
    with pytest.raises(AmbiguousLine) as caught:
        parse_position_line("Побелка, 150,5, 3000", Category.WORK)

    with Session() as db:
        await stepwise.offer_readings(message, db, UID, caught.value)
        await stepwise.handle_reading_choice(query, db, UID, "plain")
        rows = positions.load(db, UID, estimate_id)

    assert rows[0].qty == D("5")
    assert rows[0].name == "Побелка, 150"


@async_test
async def test_cancelling_an_ambiguous_line_adds_nothing(bot):
    stepwise, Session, estimate_id = bot
    message, query = FakeMessage(), FakeQuery()
    with pytest.raises(AmbiguousLine) as caught:
        parse_position_line("Побелка, 150,5, 3000", Category.WORK)

    with Session() as db:
        await stepwise.offer_readings(message, db, UID, caught.value)
        await stepwise.handle_reading_choice(query, db, UID, "cancel")
        assert positions.load(db, UID, estimate_id) == []
        assert user_state(db, UID).pending_line is None
