"""Общие генераторы и оракулы для тестов ядра."""

from __future__ import annotations

import asyncio
import functools
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import strategies as st

from smeta_core import Category, PositionData
from smeta_storage import bootstrap, build_engine, build_sessionmaker


def async_test(function):
    """Запускает корутину-тест без pytest-asyncio: лишняя зависимость не нужна."""

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


class ErrorUpdate:
    """Апдейт для общего перехвата ошибок (bot.handlers.errors.on_error).

    С Sprint 7 отказы домена — FrozenEstimateError и IntegrityError —
    объясняются одним обработчиком, а не каждым хендлером по-своему. Значит,
    и проверяются они через него.
    """

    def __init__(self, message):
        self.effective_message = message


class ErrorContext:
    def __init__(self, error):
        self.error = error


_open_engines = []


def open_storage(db_path):
    """Поднимает базу с текущей схемой. Возвращает (engine, фабрика сессий).

    Отдельный engine на вызов — так тест может честно изобразить рестарт
    процесса: выбросить старый и подняться заново на том же файле.
    """
    engine = build_engine(f"sqlite:///{db_path}")
    _open_engines.append(engine)
    bootstrap(engine)
    return engine, build_sessionmaker(engine)


@pytest.fixture(autouse=True)
def _dispose_engines():
    """Закрывает соединения после каждого теста, иначе SQLite течёт файлами."""
    yield
    while _open_engines:
        _open_engines.pop().dispose()

# Генераторы строго в границах домена (docs/money.md §1.2), в целых минорных
# единицах — так исключены значения, которые домен обязан отвергать.
qty_st = st.integers(min_value=1, max_value=99_999_999).map(
    lambda milli: Decimal(milli).scaleb(-3)
)
price_st = st.integers(min_value=0, max_value=999_999_999).map(
    lambda kop: Decimal(kop).scaleb(-2)
)
rate_st = st.integers(min_value=0, max_value=9_999).map(
    lambda bp: Decimal(bp).scaleb(-2)
)
category_st = st.sampled_from([Category.WORK, Category.MATERIAL])

# Потолок базы, при котором строка не превысит LINE_MAX ни при какой ставке:
# 5e8 * (1 + 99.99/100) = 9.9995e8 < 999 999 999.99.
_BASE_CAP = Decimal("500000000")


@st.composite
def qty_price_st(draw):
    """Пара (qty, price), заведомо укладывающаяся в потолок суммы строки."""
    qty = draw(qty_st)
    price_cap = min(999_999_999, int(_BASE_CAP / qty * 100))
    price = Decimal(draw(st.integers(min_value=0, max_value=price_cap))).scaleb(-2)
    return qty, price


@st.composite
def position_st(draw):
    qty, price = draw(qty_price_st())
    return PositionData(
        category=draw(category_st),
        name=draw(st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")),
        qty=qty,
        price=price,
    )


def excel_round(value: float, places: int = 2) -> Decimal:
    """Эмулятор функции ROUND из Excel.

    Excel округляет не точное двоичное значение double, а его десятичное
    представление на 15 значащих цифрах, half-away-from-zero. Именно поэтому
    =ROUND(2,675; 2) даёт 2,68, хотя double(2.675) строго меньше 2.675.
    """
    return Decimal(f"{value:.15g}").quantize(
        Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
    )
