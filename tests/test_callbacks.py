"""Инлайн-кнопки: каждая ветка on_callback и четыре способа нажать не вовремя.

До Sprint 7 у этого модуля не было ни одного теста, хотя для живого человека
кнопки — самый частый путь: предпросмотр, «Взять цену», «÷», подтверждения.
Непокрытая кнопка — это час чужого времени, потраченный на баг, который ловится
здесь за миллисекунду.

Проверяется четыре класса «нажали не вовремя»:

  — кнопка на смете, которую уже отправили;
  — кнопка из прошлого разговора (позиция удалена, черновик закрыт,
    предпросмотр закрыт, префикс от старой версии бота);
  — двойное нажатие;
  — кнопка с чужим id.

Последнее особенно: callback_data приходит от клиента и содержит id сметы.
uid берётся из апдейта — его нажимающий подменить не может, — но что id
сверяется с uid, до сих пор никем не проверялось.
"""

from __future__ import annotations

import os
from decimal import Decimal as D

import pytest

from conftest import async_test, open_storage
from smeta_core import Category, PositionData
from smeta_storage import (
    Estimate,
    FrozenEstimateError,
    PendingRow,
    create_estimate,
    pending,
    positions,
    send,
    set_category,
    set_current_estimate,
    update_draft,
    user_state,
)

ME = 111_111
STRANGER = 222_222


class FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.sent: list[str] = []

    async def reply_text(self, text, **_kwargs):
        self.sent.append(text)


class FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.message = FakeMessage()
        self.edits: list[str] = []
        self.answered = 0

    async def answer(self):
        self.answered += 1

    async def edit_message_text(self, text, **_kwargs):
        self.edits.append(text)

    @property
    def said(self) -> str:
        return "\n".join(self.edits + self.message.sent)


class FakeUpdate:
    def __init__(self, query: FakeQuery, uid: int = ME):
        self.callback_query = query
        self.effective_user = type("User", (), {"id": uid})()


@pytest.fixture
def bot(tmp_path, monkeypatch):
    """Бот на своей базе. Возвращает (нажать, Session)."""
    os.environ["ESTIMATE_DB_URL"] = f"sqlite:///{tmp_path / 'cb.db'}"
    _engine, Session = open_storage(tmp_path / "cb.db")

    from bot.handlers import callbacks

    monkeypatch.setattr(callbacks, "SessionLocal", Session)

    async def press(data: str, uid: int = ME) -> FakeQuery:
        query = FakeQuery(data)
        await callbacks.on_callback(FakeUpdate(query, uid), None)
        return query

    return press, Session


def an_estimate(Session, uid=ME, name="Ремонт", with_position=True):
    with Session() as db:
        estimate = create_estimate(db, uid, name=name)
        set_current_estimate(db, uid, estimate.id)
        set_category(db, uid, Category.WORK)
        if with_position:
            positions.add(db, uid, estimate.id, PositionData(
                Category.WORK, "Побелка", D("150"), D("3000"), "м²"))
        db.commit()
        return estimate.id


def a_preview(Session, estimate_id, uid=ME, rows=None):
    with Session() as db:
        pending.replace(db, uid, estimate_id, rows or [
            PendingRow(category="work", name="Стяжка", qty="40", price="700",
                       unit="м²", unit_spoken="метров"),
        ])


# --- Кнопка всегда отвечает ---


@async_test
async def test_the_spinner_always_stops(bot):
    """query.answer() зовётся раньше всякой логики: иначе кнопка «думает»."""
    press, Session = bot
    an_estimate(Session)
    for data in ("ai:cancel", "draft:cancel", "чтототакое:1", "clear_no:1"):
        query = await press(data)
        assert query.answered == 1, data


@async_test
async def test_an_unknown_button_says_so_instead_of_going_quiet(bot):
    """Молчание человек читает как поломку и жмёт ещё несколько раз."""
    press, Session = bot
    estimate_id = an_estimate(Session)
    query = await press(f"откуда_это:{estimate_id}")
    assert "устарела" in query.said


# --- Чужое ---


@pytest.mark.parametrize("prefix", ["clear_yes", "renew_yes", "revoke_yes", "relink_yes", "renew"])
@async_test
async def test_a_button_carrying_someone_elses_estimate_is_refused(bot, prefix):
    """callback_data содержит id — и он обязан принадлежать нажавшему."""
    press, Session = bot
    an_estimate(Session, uid=ME)
    theirs = an_estimate(Session, uid=STRANGER, name="Чужая")

    query = await press(f"{prefix}:{theirs}", uid=ME)
    assert query.said == "Смета не найдена."

    with Session() as db:
        assert len(positions.load(db, STRANGER, theirs)) == 1, "чужие позиции целы"


@async_test
async def test_the_preview_of_one_user_is_invisible_to_another(bot):
    """Ordinal чужого предпросмотра не находится: выборка идёт по uid."""
    press, Session = bot
    mine = an_estimate(Session, uid=ME)
    theirs = an_estimate(Session, uid=STRANGER, name="Чужая")
    a_preview(Session, mine, uid=ME)
    a_preview(Session, theirs, uid=STRANGER, rows=[
        PendingRow(category="work", name="Их работа", qty="1", price="999"),
    ])

    await press("ai:drop:1", uid=ME)
    with Session() as db:
        assert len(pending.load(db, STRANGER)) == 1, "чужой предпросмотр не тронут"
        assert not pending.load(db, ME)


@pytest.mark.parametrize("data", ["clear_yes:abc", "clear_yes:", "renew:-1", "clear_yes:999999"])
@async_test
async def test_a_button_with_nonsense_instead_of_an_id_does_not_crash(bot, data):
    """Кнопка приходит от клиента: числом её содержимое никто не обещал."""
    press, Session = bot
    an_estimate(Session)
    query = await press(data)
    assert query.said == "Смета не найдена."


# --- Смета уже отправлена ---


@async_test
async def test_adding_a_preview_to_a_sent_estimate_keeps_the_preview(bot):
    """Человек это продиктовал — терять надиктованное из-за статуса нельзя."""
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id)
    with Session() as db:
        send(db, db.get(Estimate, estimate_id))

    query = await press("ai:add")
    assert "не меняется" in query.said
    assert "/revise" in query.said
    assert not query.edits, "сообщение с кнопками не переписываем — они ещё нужны"

    with Session() as db:
        assert len(pending.load(db, ME)) == 1, "предпросмотр остался"
        assert len(positions.load(db, ME, estimate_id)) == 1, "в смету ничего не попало"


@async_test
async def test_clearing_a_sent_estimate_refuses_through_the_guard(bot):
    """Охрана в репозитории, а не в хендлере: отказ доходит до общего перехвата."""
    press, Session = bot
    estimate_id = an_estimate(Session)
    with Session() as db:
        send(db, db.get(Estimate, estimate_id))

    with pytest.raises(FrozenEstimateError):
        await press(f"clear_yes:{estimate_id}")

    with Session() as db:
        assert len(positions.load(db, ME, estimate_id)) == 1


@async_test
async def test_renewing_from_a_sent_estimate_is_allowed(bot):
    """«Обновить» делает НОВУЮ смету и старую не трогает — запрета здесь нет."""
    press, Session = bot
    estimate_id = an_estimate(Session)
    with Session() as db:
        send(db, db.get(Estimate, estimate_id))

    query = await press(f"renew_yes:{estimate_id}")
    assert "Создана и активирована" in query.said
    with Session() as db:
        assert db.get(Estimate, estimate_id).status == "sent"


# --- Двойное нажатие ---


@async_test
async def test_pressing_add_twice_does_not_report_zero(bot):
    """«Добавлено: 0» человек прочтёт как «ничего не вышло» и продиктует заново."""
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id)

    first = await press("ai:add")
    assert "Добавлено позиций: <b>1</b>" in first.said

    second = await press("ai:add")
    assert "уже закрыт" in second.said
    with Session() as db:
        assert len(positions.load(db, ME, estimate_id)) == 2, "второе нажатие ничего не добавило"


@async_test
async def test_pressing_cancel_twice_is_harmless(bot):
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id)

    assert "отменён" in (await press("ai:cancel")).said
    assert "отменён" in (await press("ai:cancel")).said


@async_test
async def test_dropping_the_same_row_twice_is_harmless(bot):
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id, rows=[
        PendingRow(category="work", name="Первая", qty="1", price="100"),
        PendingRow(category="work", name="Вторая", qty="2", price="200"),
    ])

    await press("ai:drop:1")
    await press("ai:drop:1")
    with Session() as db:
        left = [row.name for row in pending.load(db, ME)]
    assert left == ["Вторая"]


# --- Кнопка из прошлого разговора ---


@pytest.mark.parametrize("data", ["ai:drop:99", "ai:hint:99", "ai:hintmed:99",
                                  "ai:split:99", "ai:dosplit:99"])
@async_test
async def test_a_button_pointing_at_a_row_that_is_gone_shows_the_preview(bot, data):
    """Строку удалили раньше — предпросмотр перерисовывается, а не падает."""
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id)

    query = await press(data)
    assert "Распознала позиций" in query.said
    with Session() as db:
        assert len(pending.load(db, ME)) == 1, "ничего не потерялось"


@async_test
async def test_a_unit_button_from_an_old_message_does_not_hijack_the_next_one(bot):
    """Без проверки нажатие заводило черновик на шаге «цена».

    Дальше любое сообщение человека — о чём угодно — уходило в цену позиции,
    которой он не начинал. Найдено прогоном кнопок, а не чтением кода.
    """
    press, Session = bot
    an_estimate(Session)

    query = await press("unit:шт")
    assert "устарела" in query.said
    with Session() as db:
        assert user_state(db, ME).draft_step is None, "черновик не должен появиться"


@async_test
async def test_a_draft_button_from_an_old_message_says_so(bot):
    press, Session = bot
    an_estimate(Session)
    query = await press("draft:add")
    assert "устарела" in query.said
    assert "/add" in query.said


@async_test
async def test_cancelling_a_draft_that_is_already_gone_is_harmless(bot):
    """«Отменить» обязана работать всегда: это выход, а не действие."""
    press, Session = bot
    an_estimate(Session)
    query = await press("draft:cancel")
    assert "Отменено" in query.said


@async_test
async def test_a_reading_choice_after_the_line_is_gone_says_it_was_skipped(bot):
    press, Session = bot
    an_estimate(Session)
    query = await press("pick:plain")
    assert "пропущена" in query.said


# --- Обычная работа каждой ветки ---


@async_test
async def test_mode_buttons(bot):
    press, Session = bot
    an_estimate(Session)

    step = await press("mode:step")
    assert "по шагам" in step.said
    with Session() as db:
        assert user_state(db, ME).draft_step == "name"

    bulk = await press("mode:bulk")
    assert "построчно" in bulk.said


@async_test
async def test_the_unit_button_moves_the_draft_to_the_price_step(bot):
    press, Session = bot
    an_estimate(Session)
    with Session() as db:
        update_draft(db, ME, draft_step="unit", draft_name="Стяжка", draft_qty_milli=40_000)

    query = await press("unit:м²")
    assert "Цена за единицу" in query.said
    with Session() as db:
        state = user_state(db, ME)
        assert (state.draft_unit, state.draft_step) == ("м²", "price")


@async_test
async def test_skipping_the_unit_substitutes_the_one_for_the_category(bot):
    press, Session = bot
    an_estimate(Session)
    with Session() as db:
        update_draft(db, ME, draft_step="unit", draft_name="Стяжка", draft_qty_milli=40_000)

    query = await press("unit:-")
    assert "подставлена по категории" in query.said


@async_test
async def test_the_draft_add_button_writes_the_position(bot):
    press, Session = bot
    estimate_id = an_estimate(Session, with_position=False)
    with Session() as db:
        update_draft(db, ME, draft_step="confirm", draft_name="Стяжка",
                     draft_qty_milli=40_000, draft_price_kop=70_000, draft_unit="м²")

    query = await press("draft:add")
    assert "Добавлено: Стяжка" in query.said
    with Session() as db:
        [row] = positions.load(db, ME, estimate_id)
        assert (row.name, row.qty, row.price) == ("Стяжка", D("40"), D("700"))


@async_test
async def test_the_draft_restart_button_starts_over(bot):
    press, Session = bot
    an_estimate(Session)
    with Session() as db:
        update_draft(db, ME, draft_step="qty", draft_name="Ошибка")

    query = await press("draft:restart")
    assert "Что добавляем" in query.said
    with Session() as db:
        state = user_state(db, ME)
        assert (state.draft_step, state.draft_name) == ("name", None)


@async_test
async def test_taking_the_hinted_price_puts_it_in_the_row(bot):
    """💡 «Взять цену» — цена появляется только по нажатию (ADR-017)."""
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id, rows=[
        PendingRow(category="material", name="Цемент", qty="20", price="",
                   unit="", unit_spoken="мешков", problem="Цена: не указана",
                   hint_price="380.00", hint_median="375.00", hint_times=4),
    ])

    query = await press("ai:hint:1")
    assert "Распознала позиций" in query.said
    with Session() as db:
        [row] = pending.load(db, ME)
        assert row.price == "380.00"
        assert row.problem is None, "причина снимается вместе с ценой"


@async_test
async def test_taking_the_median_puts_the_median_in_the_row(bot):
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id, rows=[
        PendingRow(category="material", name="Цемент", qty="20", price="",
                   unit="", unit_spoken="мешков", problem="Цена: не указана",
                   hint_price="380.00", hint_median="375.00", hint_times=4),
    ])

    await press("ai:hintmed:1")
    with Session() as db:
        [row] = pending.load(db, ME)
        assert row.price == "375.00"


@async_test
async def test_the_split_button_offers_and_then_divides(bot):
    """÷ «за всё»: сначала показывается потеря копеек, потом делится."""
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id, rows=[
        PendingRow(category="material", name="Плитка", qty="1", price="9000",
                   unit_spoken="шт", price_scope="total",
                   total_price="9000", total_qty="7", total_unit="шт"),
    ])

    offered = await press("ai:split:1")
    assert "Сказано:" in offered.said and "Если разбить" in offered.said

    await press("ai:dosplit:1")
    with Session() as db:
        [row] = pending.load(db, ME)
        assert (row.qty, row.price) == ("7.000", "1285.71")
        assert row.total_price is None, "вопрос закрыт человеком"


@async_test
async def test_the_back_button_returns_to_the_preview(bot):
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id)
    query = await press("ai:back")
    assert "Распознала позиций" in query.said


@async_test
async def test_dropping_the_last_row_closes_the_preview(bot):
    press, Session = bot
    estimate_id = an_estimate(Session)
    a_preview(Session, estimate_id)
    query = await press("ai:drop:1")
    assert "отменён" in query.said


@async_test
async def test_the_renew_button_asks_before_it_acts(bot):
    press, Session = bot
    estimate_id = an_estimate(Session)
    query = await press(f"renew:{estimate_id}")
    assert "Обновить смету" in query.said
    with Session() as db:
        assert len(list(db.execute(
            __import__("sqlalchemy").select(Estimate).where(Estimate.user_id == ME)
        ).scalars())) == 1, "до подтверждения ничего не создаётся"


@pytest.mark.parametrize("prefix", ["renew", "clear", "revoke", "relink"])
@async_test
async def test_saying_no_does_nothing(bot, prefix):
    press, Session = bot
    estimate_id = an_estimate(Session)
    query = await press(f"{prefix}_no:{estimate_id}")
    assert query.said == "Отменено."
    with Session() as db:
        assert len(positions.load(db, ME, estimate_id)) == 1


@async_test
async def test_the_clear_button_empties_the_draft_estimate(bot):
    press, Session = bot
    estimate_id = an_estimate(Session)
    query = await press(f"clear_yes:{estimate_id}")
    assert "Очищены позиции" in query.said
    with Session() as db:
        assert not positions.load(db, ME, estimate_id)
