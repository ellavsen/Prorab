"""Предпросмотр распознанной пачки (ADR-012).

Главное свойство: между моделью и сметой всегда стоит человек. Ни один тест
здесь не поднимает Telegram и не ходит в сеть — провайдером служит стаб.
"""

import os
from decimal import Decimal as D

import pytest

from conftest import async_test, open_storage
from smeta_ai import (
    Extraction,
    ExtractionStatus,
    FieldStatus,
    PositionCandidate,
    Price,
    PriceScope,
    Quantity,
)
from smeta_storage import create_estimate, pending, positions, set_category, set_current_estimate

UID = 77

SPEECH = "побелка 150 квадратов по 3000 и гвозди 1000 штук по 20"


class FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.sent: list[str] = []
        self.keyboards: list[object] = []
        self.voice = None
        self.photo: list[object] = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(text)
        self.keyboards.append(kwargs.get("reply_markup"))
        return self

    @property
    def last(self) -> str:
        return self.sent[-1].replace("\xa0", " ")


class FakeQuery:
    def __init__(self):
        self.message = FakeMessage()
        self.edited: list[str] = []
        self.keyboards: list[object] = []

    async def edit_message_text(self, text, **kwargs):
        self.edited.append(text)
        self.keyboards.append(kwargs.get("reply_markup"))

    @property
    def last(self) -> str:
        return self.edited[-1].replace("\xa0", " ")


class FakeFile:
    async def download_as_bytearray(self):
        return bytearray(b"fake-audio")


class FakeMedia:
    async def get_file(self):
        return FakeFile()


class FakeUser:
    id = UID


class FakeUpdate:
    def __init__(self, message):
        self.message = message
        self.effective_user = FakeUser()


@pytest.fixture
def bot(tmp_path, monkeypatch):
    """Бот с базой во временном файле и заведомо стабовым AI-слоем.

    Пустой OPENAI_API_KEY ставится ДО импорта: load_dotenv не перезаписывает
    уже заданные переменные, поэтому реальный .env не утащит тесты в сеть.
    """
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["ESTIMATE_DB_URL"] = f"sqlite:///{tmp_path / 'ai.db'}"
    _engine, Session = open_storage(tmp_path / "ai.db")

    from bot.handlers import ai, preview
    from bot.handlers import positions as positions_handlers
    from bot.provider import PROVIDER

    assert PROVIDER.name == "stub", "тесты не должны ходить в живую модель"
    monkeypatch.setattr(ai, "SessionLocal", Session)
    monkeypatch.setattr(positions_handlers, "SessionLocal", Session)

    with Session() as db:
        estimate = create_estimate(db, UID, name="Смета")
        set_current_estimate(db, UID, estimate.id)
        set_category(db, UID, "work")
    return ai, preview, positions_handlers, Session, estimate.id


def _unpack(bot):
    ai, preview, _positions_handlers, Session, estimate_id = bot
    return ai, preview, Session, estimate_id


def candidates(*items):
    """Ответ модели во вложенной схеме: строки, статусы, scope."""
    positions = tuple(
        PositionCandidate(
            name=item["name"],
            qty=Quantity(status=FieldStatus.STATED, value=item["qty"]),
            price=Price(status=FieldStatus.STATED, scope=PriceScope.PER_UNIT,
                        value=item["price"]),
            unit=item.get("unit", ""),
            category=item["category"],
            source_quote=item["name"],
        )
        for item in items
    )
    return Extraction(status=ExtractionStatus.OK, positions=positions)


@async_test
async def test_recognized_positions_do_not_reach_the_estimate(bot):
    """Тезис проекта: LLM никогда не пишет в смету напрямую."""
    ai, _preview, _positions_handlers, Session, estimate_id = bot
    message = FakeMessage()

    with Session() as db:
        await ai.extract_and_offer(message, db, UID, SPEECH)

        assert len(pending.load(db, UID)) == 2
        assert positions.load(db, UID, estimate_id) == []


@async_test
async def test_preview_shows_the_total_with_markup(bot):
    ai, _preview, Session, _ = _unpack(bot)
    message = FakeMessage()
    with Session() as db:
        await ai.extract_and_offer(message, db, UID, SPEECH)

    # 150 × 3000 = 450 000 и 1000 × 20 = 20 000, с наценкой 6% — 498 200,00.
    assert "477000,00" in message.last and "21200,00" in message.last
    assert "498200,00" in message.last
    assert "В смету пока ничего не добавлено" in message.last


@async_test
async def test_confirmation_adds_everything(bot):
    ai, preview, Session, estimate_id = _unpack(bot)
    message, query = FakeMessage(), FakeQuery()

    with Session() as db:
        await ai.extract_and_offer(message, db, UID, SPEECH)
        await preview.handle_action(query, db, UID, "add")

        rows = positions.load(db, UID, estimate_id)
        assert pending.load(db, UID) == []

    assert [row.name for row in rows] == ["Побелка", "Гвозди"]
    assert "Добавлено позиций: <b>2</b>" in query.last


@async_test
async def test_cancelling_adds_nothing(bot):
    ai, preview, Session, estimate_id = _unpack(bot)
    message, query = FakeMessage(), FakeQuery()
    with Session() as db:
        await ai.extract_and_offer(message, db, UID, SPEECH)
        await preview.handle_action(query, db, UID, "cancel")

        assert positions.load(db, UID, estimate_id) == []
        assert pending.load(db, UID) == []


@async_test
async def test_dropping_a_line_keeps_the_numbers_of_the_others(bot):
    """Перенумерация меняла бы подписи кнопок под пальцами у человека."""
    ai, preview, Session, estimate_id = _unpack(bot)
    message, query = FakeMessage(), FakeQuery()

    with Session() as db:
        await ai.extract_and_offer(message, db, UID, SPEECH)
        await preview.handle_action(query, db, UID, "drop:1")

        remaining = pending.load(db, UID)
        assert [row.ordinal for row in remaining] == [2]
        assert [row.name for row in remaining] == ["Гвозди"]

        await preview.handle_action(query, db, UID, "add")
        rows = positions.load(db, UID, estimate_id)

    assert [row.name for row in rows] == ["Гвозди"]


@async_test
async def test_a_position_the_domain_rejects_is_shown_with_a_reason(bot):
    _ai, preview, Session, estimate_id = _unpack(bot)
    message, query = FakeMessage(), FakeQuery()
    broken = candidates(
        {"name": "Побелка", "qty": "150", "price": "3000", "unit": "м2", "category": "work"},
        {"name": "Цемент", "qty": "0", "price": "450", "unit": "шт", "category": "material"},
    )

    with Session() as db:
        await preview.offer(message, db, UID, broken)
        assert "Не разобрала" in message.last
        assert "Цемент" in message.last

        await preview.handle_action(query, db, UID, "add")
        rows = positions.load(db, UID, estimate_id)

    assert [row.name for row in rows] == ["Побелка"]
    assert "Не добавлено: 1" in query.last


@async_test
async def test_a_phrase_without_positions_says_so(bot):
    ai, _preview, Session, _ = _unpack(bot)
    message = FakeMessage()
    with Session() as db:
        await ai.extract_and_offer(message, db, UID, "Привет, как дела?")
        assert pending.load(db, UID) == []
    assert "Позиций тут не нашла" in message.last


@async_test
async def test_a_new_recognition_replaces_the_previous_preview(bot):
    ai, _preview, Session, _ = _unpack(bot)
    message = FakeMessage()
    with Session() as db:
        await ai.extract_and_offer(message, db, UID, SPEECH)
        await ai.extract_and_offer(message, db, UID, "стяжка 40 квадратов по 1200")

        rows = pending.load(db, UID)
    assert [row.name for row in rows] == ["Стяжка"]


@async_test
async def test_voice_message_goes_all_the_way_to_the_preview(bot):
    """DEMO-режим целиком: голос -> расшифровка -> кандидаты -> предпросмотр."""
    ai, _preview, Session, estimate_id = _unpack(bot)
    message = FakeMessage()
    message.voice = FakeMedia()

    await ai.on_voice(FakeUpdate(message), None)

    assert any("DEMO-режим" in text for text in message.sent)
    assert any("Услышала" in text for text in message.sent)
    with Session() as db:
        assert len(pending.load(db, UID)) == 2
        assert positions.load(db, UID, estimate_id) == []


@async_test
async def test_photo_goes_all_the_way_to_the_preview(bot):
    ai, _preview, Session, estimate_id = _unpack(bot)
    message = FakeMessage()
    message.photo = [FakeMedia()]

    await ai.on_photo(FakeUpdate(message), None)

    with Session() as db:
        assert [row.name for row in pending.load(db, UID)] == ["Цемент М500", "Песок карьерный"]
        assert positions.load(db, UID, estimate_id) == []


@async_test
async def test_free_speech_falls_through_to_the_ai_layer(bot):
    """Строгий формат не сработал — разбирает модель, а не сыплются ошибки."""
    _ai, _preview, positions_handlers, Session, estimate_id = bot
    message = FakeMessage(text="побелка 150 квадратов по 3000")

    await positions_handlers.on_text(FakeUpdate(message), None)

    with Session() as db:
        assert [row.name for row in pending.load(db, UID)] == ["Побелка"]
        assert positions.load(db, UID, estimate_id) == []
    assert not any("Не удалось добавить строку" in text for text in message.sent)


@async_test
async def test_the_strict_format_still_wins(bot):
    """Каноническая строка добавляется сразу, без предпросмотра пачки."""
    _ai, _preview, positions_handlers, Session, estimate_id = bot
    message = FakeMessage(text="Побелка, 150 м2, 3000")

    await positions_handlers.on_text(FakeUpdate(message), None)

    with Session() as db:
        assert pending.load(db, UID) == []
        assert [row.name for row in positions.load(db, UID, estimate_id)] == ["Побелка"]


# --- «За всё» схлопывается, разбить можно только явно (ADR-012) ---

def total_scope_extraction():
    """Модель услышала «на тридцать тысяч за всё» и не стала делить."""
    return Extraction(status=ExtractionStatus.OK, positions=(
        PositionCandidate(
            name="Покраска",
            qty=Quantity(status=FieldStatus.STATED, value="7"),
            price=Price(status=FieldStatus.STATED, scope=PriceScope.TOTAL,
                        value="30000"),
            unit="", unit_spoken="комнат", category="work",
            source_quote="покраска семь комнат на тридцать тысяч за всё",
        ),
    ))


@async_test
async def test_price_for_everything_keeps_the_sum_exactly(bot):
    _ai, preview, Session, estimate_id = _unpack(bot)
    message, query = FakeMessage(), FakeQuery()

    with Session() as db:
        await preview.offer(message, db, UID, total_scope_extraction())
        row = pending.load(db, UID)[0]

        assert row.name == "Покраска (7 комнат)"
        assert (row.qty, row.price) == ("1.000", "30000.00")  # масштаб домена

        await preview.handle_action(query, db, UID, "add")
        rows = positions.load(db, UID, estimate_id)

    # Названное число дошло до сметы копейка в копейку.
    assert rows[0].price == D("30000.00")
    assert rows[0].qty == D("1")


@async_test
async def test_splitting_shows_the_loss_before_applying(bot):
    _ai, preview, Session, _ = _unpack(bot)
    message, query = FakeMessage(), FakeQuery()

    with Session() as db:
        await preview.offer(message, db, UID, total_scope_extraction())
        await preview.handle_action(query, db, UID, "split:1")

        # Ничего ещё не поменялось — только показано.
        assert pending.load(db, UID)[0].qty == "1.000"

    assert "4285,71" in query.last
    assert "0,03" in query.last


@async_test
async def test_splitting_applies_only_on_confirmation(bot):
    _ai, preview, Session, _ = _unpack(bot)
    message, query = FakeMessage(), FakeQuery()

    with Session() as db:
        await preview.offer(message, db, UID, total_scope_extraction())
        await preview.handle_action(query, db, UID, "split:1")
        await preview.handle_action(query, db, UID, "dosplit:1")
        row = pending.load(db, UID)[0]

    assert row.name == "Покраска"          # суффикс снят ровно тот, что добавляли
    assert (row.qty, row.price) == ("7.000", "4285.71")
    assert row.unit_spoken == "комнат"


@async_test
async def test_declining_the_split_leaves_the_line_alone(bot):
    _ai, preview, Session, _ = _unpack(bot)
    message, query = FakeMessage(), FakeQuery()

    with Session() as db:
        await preview.offer(message, db, UID, total_scope_extraction())
        await preview.handle_action(query, db, UID, "split:1")
        await preview.handle_action(query, db, UID, "back")
        row = pending.load(db, UID)[0]

    assert (row.name, row.qty, row.price) == ("Покраска (7 комнат)", "1.000", "30000.00")


@async_test
async def test_the_spoken_unit_reaches_the_estimate(bot):
    """Заказчик должен увидеть «мешков», а не канон (ADR-015)."""
    _ai, preview, Session, estimate_id = _unpack(bot)
    message, query = FakeMessage(), FakeQuery()
    said = Extraction(status=ExtractionStatus.OK, positions=(
        PositionCandidate(
            name="Цемент",
            qty=Quantity(status=FieldStatus.STATED, value="20"),
            price=Price(status=FieldStatus.STATED, scope=PriceScope.PER_UNIT,
                        value="350"),
            unit="", unit_spoken="мешков", category="material",
            source_quote="цемент 20 мешков по 350",
        ),
    ))

    with Session() as db:
        await preview.offer(message, db, UID, said)
        assert "20 мешков" in message.last
        await preview.handle_action(query, db, UID, "add")
        row = positions.load(db, UID, estimate_id)[0]

    assert row.unit_spoken == "мешков"
    assert row.unit == "шт"        # канон подставлен по категории, он для аналитики
