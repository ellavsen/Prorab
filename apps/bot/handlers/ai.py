"""Точки входа AI-слоя: голос, фото и живая речь.

Всё сходится в один путь — сырьё → кандидаты → предпросмотр → подтверждение.
Показывает и добавляет уже preview.py; здесь только разговор с провайдером.
"""

from __future__ import annotations

import asyncio

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..database import SessionLocal
from ..provider import DEMO, PROVIDER
from ..texts import (
    AI_DEMO_NOTE,
    AI_FAILED,
    AI_LISTENING,
    AI_LOOKING,
    AI_NOTHING,
    render_recognized,
)
from .preview import offer

PHOTO_MEDIA_TYPE = "image/jpeg"


async def _call(message: Message, function, *args):
    """Сетевой вызов в отдельном потоке: он не должен держать общий цикл.

    Ловится всё: SDK и сеть бросают что угодно, а падение хендлера выглядит
    для человека как молчание бота.
    """
    try:
        return await asyncio.to_thread(function, *args)
    except Exception as error:  # noqa: BLE001
        await message.reply_text(AI_FAILED.format(reason=error))
        return None


async def demo_note(message: Message) -> None:
    if DEMO:
        await message.reply_text(AI_DEMO_NOTE)


async def extract_and_offer(message: Message, db, uid: int, text: str) -> None:
    extraction = await _call(message, PROVIDER.extract, text)
    if extraction is None:
        return
    await offer(message, db, uid, extraction, source=text)


async def on_voice(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    message, uid = update.message, update.effective_user.id
    await demo_note(message)
    await message.reply_text(AI_LISTENING)

    audio = bytes(await (await message.voice.get_file()).download_as_bytearray())
    text = await _call(message, PROVIDER.transcribe, audio, "voice.ogg")
    if text is None:
        return
    if not text.strip():
        await message.reply_text(AI_NOTHING)
        return

    await message.reply_text(render_recognized(text), parse_mode=ParseMode.HTML)
    with SessionLocal() as db:
        await extract_and_offer(message, db, uid, text)


async def on_photo(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    message, uid = update.message, update.effective_user.id
    await demo_note(message)
    await message.reply_text(AI_LOOKING)

    largest = message.photo[-1]
    image = bytes(await (await largest.get_file()).download_as_bytearray())
    extraction = await _call(message, PROVIDER.extract_from_image, image, PHOTO_MEDIA_TYPE)
    if extraction is None:
        return

    # Вход не текстовый: цитаты сверять не с чем, source остаётся None.
    with SessionLocal() as db:
        await offer(message, db, uid, extraction)
