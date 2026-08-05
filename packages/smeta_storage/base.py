"""Общее основание таблиц: declarative base, время и наценка по умолчанию.

Отдельным файлом, потому что таблицы живут в двух модулях — документ в
models.py, всё остальное в records.py, — и оба должны брать `Base` из одного
места. Импортировать его из соседа значило бы завести цикл.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase

# Наценка по умолчанию для НОВЫХ смет, в базисных пунктах: 600 = 6.00%.
# Копируется в смету при создании и дальше живёт в документе (ADR-003).
DEFAULT_MARKUP_BP = 600


def utcnow() -> datetime:
    """Наивный UTC.

    datetime.utcnow() устарел в 3.12. Значение с таймзоной поменяло бы формат
    хранения в SQLite и сломало бы сортировку по смешанной базе, поэтому
    оставляем наивный UTC, но получаем его не устаревшим способом.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass
