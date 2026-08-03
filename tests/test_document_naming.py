"""Имя файла — тоже то, что уходит наружу (ADR-001).

Дефект, который эти тесты закрывают, прожил в проекте с Sprint 0: ADR-001
удалил из репозитория экспортированный XLSX с `user_id` в имени, но код,
который это имя порождал, остался. Пока файл уходил автору, ошибка была
почти незаметной — но документ пересылают заказчику, и вместе с ним уезжал
Telegram-идентификатор владельца.
"""

import os
from datetime import date, datetime
from decimal import Decimal as D

import pytest
from telegram import InputFile

from conftest import async_test, open_storage
from smeta_core import Category, PositionData
from smeta_export import document_filename
from smeta_storage import create_estimate, positions, set_current_estimate

UID = 527183940  # длинный, как настоящий telegram id: его легко искать в строке


def test_the_name_carries_the_estimate_number_and_the_date():
    assert document_filename(3, "xlsx", on=date(2026, 8, 3)) == "smeta_no3_20260803.xlsx"


def test_a_version_appears_only_when_there_is_one():
    """Версий пока нет; писать v1 до их появления значило бы соврать в имени."""
    assert document_filename(3, "pdf", on=date(2026, 8, 3), version=2) == (
        "smeta_no3_v2_20260803.pdf"
    )


def test_the_extension_is_accepted_with_or_without_a_dot():
    assert document_filename(1, ".pdf", on=date(2026, 1, 9)).endswith(".pdf")


def test_the_signature_has_nowhere_to_put_a_user_id():
    """Главная защита — не проверка, а подпись: лишнее просто некуда передать."""
    with pytest.raises(TypeError):
        document_filename(3, "xlsx", on=date(2026, 8, 3), user_id=UID)


class FakeDocumentMessage:
    def __init__(self):
        self.documents: list[InputFile] = []
        self.sent: list[str] = []

    async def reply_text(self, text, **_kwargs):
        self.sent.append(text)

    async def reply_document(self, document, caption="", **_kwargs):
        self.documents.append(document)
        self.sent.append(caption)


class FakeUser:
    id = UID


class FakeUpdate:
    def __init__(self, message):
        self.message = message
        self.effective_user = FakeUser()


@async_test
async def test_the_exported_file_does_not_carry_the_owner_id(tmp_path, monkeypatch):
    os.environ["ESTIMATE_DB_URL"] = f"sqlite:///{tmp_path / 'files.db'}"
    _engine, Session = open_storage(tmp_path / "files.db")

    from bot.handlers import files

    monkeypatch.setattr(files, "SessionLocal", Session)
    with Session() as db:
        estimate = create_estimate(db, UID, name="Смета")
        set_current_estimate(db, UID, estimate.id)
        positions.add(db, UID, estimate.id, PositionData(
            category=Category.MATERIAL, name="Цемент", qty=D("1"), price=D("100"), unit="шт",
        ))
        db.commit()

    message = FakeDocumentMessage()
    await files.cmd_generate(FakeUpdate(message), None)

    [document] = message.documents
    assert document.filename == f"smeta_no{estimate.number}_{datetime.now().astimezone():%Y%m%d}.xlsx"
    assert str(UID) not in document.filename
    assert str(UID) not in " ".join(message.sent), "id не должен утечь и в подпись"
