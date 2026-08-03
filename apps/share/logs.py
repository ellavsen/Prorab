"""Токен в журнале — это выданная наружу ссылка.

Адрес страницы и есть секрет: кто его знает, тот видит смету. Обычный
access-log пишет полный путь, то есть каждое открытие сметы оставляет
работающую ссылку в файле, который потом попадает в архив, в систему сбора
логов и в тикет со скриншотом. Поэтому путь режется до `/e/***` до того, как
запись уйдёт в обработчик.

Фильтр ставится и на свой журнал, и на uvicorn.access: последний пишет мимо
приложения, и одной вежливой договорённости здесь мало.
"""

from __future__ import annotations

import logging
import re

# Токен — один сегмент пути после /e/. Хвост вроде /approve сохраняется:
# «что сделали» из журнала пропадать не должно, из него уходит только «с чем».
TOKEN_IN_PATH = re.compile(r"(/e/)[^/?\s\"']+")

REDACTED = r"\1***"

LOGGERS = ("uvicorn.access", "prorab.share")


def redact(line: str) -> str:
    return TOKEN_IN_PATH.sub(REDACTED, line)


class RedactToken(logging.Filter):
    """Правит запись на месте: и шаблон, и подставляемые значения.

    uvicorn складывает путь в args, свои сообщения обычно кладут его туда же.
    Фильтр ничего не отбрасывает — он всегда пропускает запись, изменив её.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact(value) if isinstance(value, str) else value
                for value in record.args
            )
        return True


def install(*names: str) -> None:
    """Идемпотентно: повторный импорт не плодит фильтры."""
    for name in names or LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactToken) for item in logger.filters):
            logger.addFilter(RedactToken())
