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


def openai_key() -> str | None:
    """Ключ AI-слоя. Его отсутствие — не ошибка: без него включается стаб."""
    return os.getenv("OPENAI_API_KEY") or None


def unit_blocking_enabled() -> bool:
    """Запрещать ли подстановку цены без подтверждённой единицы (ADR-015).

    По умолчанию включено. Флаг существует, чтобы выключить проверку без
    правки кода, если она окажется навязчивой.
    """
    return os.getenv("UNIT_BLOCKING_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
