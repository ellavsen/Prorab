"""Конфигурация. Единственное место, где читается окружение."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("prorab")


def require_token() -> str:
    """Токен нужен только при запуске бота, поэтому проверка не в импорте.

    Раньше отсутствие токена валило импорт модуля, из-за чего его нельзя было
    ни протестировать, ни просто прочитать через python -c.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN в окружении. Проверь .env")
    return token
