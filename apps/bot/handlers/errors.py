"""Отказ домена — это ответ человеку, а не молчание и traceback в консоли.

Два отказа приходят с любого пути и всегда объясняются одинаково:

  — FrozenEstimateError: отправленную смету менять нельзя. Охрана живёт в
    smeta_storage.guards и срабатывает на любом пути записи, а их больше
    десятка. Ловить её в каждом хендлере значило бы вернуть ту забывчивость,
    ради которой охрану и вынесли из хендлеров.
  — IntegrityError: данные разошлись со слепком. Приходит отовсюду, где
    показывается сумма, и ответ везде один — иначе /list покажет итог, а /pdf
    по той же смете откажется его выдать, и разницу нечем объяснить.

Поэтому перехват один, на всё приложение. До Sprint 7 ни то, ни другое не
было достижимо из бота: перевести смету в SENT было нечем.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from smeta_core import IntegrityError
from smeta_storage import FrozenEstimateError

from ..texts import INTEGRITY_BROKEN

logger = logging.getLogger("prorab")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    message = getattr(update, "effective_message", None)

    if message is not None:
        if isinstance(error, FrozenEstimateError):
            await message.reply_text(str(error))
            return
        if isinstance(error, IntegrityError):
            await message.reply_text(INTEGRITY_BROKEN.format(reason=error))
            return

    logger.error("Ошибка в обработчике: %s", error, exc_info=error)
    if isinstance(update, Update) and message is not None:
        await message.reply_text("Что-то пошло не так. Попробуйте ещё раз.")
