"""Отказ охраны — это ответ человеку, а не молчание и traceback в консоли.

Запрет менять отправленную смету живёт в smeta_storage.guards и срабатывает
на любом пути записи — их больше десятка. Ловить FrozenEstimateError в каждом
хендлере значило бы вернуть ту самую забывчивость, ради которой охрану
и вынесли из хендлеров. Поэтому перехват один, на всё приложение.

До Sprint 7 это не было заметно: перевести смету в SENT из бота было нечем.
С появлением /send путь стал достижимым.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from smeta_storage import FrozenEstimateError

logger = logging.getLogger("prorab")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    message = getattr(update, "effective_message", None)

    if isinstance(error, FrozenEstimateError) and message is not None:
        await message.reply_text(str(error))
        return

    logger.error("Ошибка в обработчике: %s", error, exc_info=error)
    if isinstance(update, Update) and message is not None:
        await message.reply_text("Что-то пошло не так. Попробуйте ещё раз.")
