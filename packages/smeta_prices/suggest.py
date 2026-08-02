"""Подсказка цены: что показать человеку и когда молчать.

Порядок источников — своя история, потом рынок, потом ничего (ADR-017).
Рынка в 6a нет вовсе, поэтому здесь ровно первая ветка: своих цен нет —
подсказки нет. Выдуманного числа не будет ни при каких условиях.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .stats import median

# Ниже этого числа вхождений медиана не показывается: на двух точках она
# равна среднему, и одна опечатка двигает её наполовину (ADR-018).
MIN_FOR_MEDIAN = 3


@dataclass(frozen=True)
class PricePoint:
    """Своя цена за единицу, когда-то введённая руками."""

    price: Decimal
    on: date
    unit_spoken: str = ""


@dataclass(frozen=True)
class Hint:
    """Что показать. Кнопка по умолчанию — last: ближе к сегодняшнему поставщику."""

    last: Decimal
    on: date
    times: int
    unit_spoken: str = ""
    median: Decimal | None = None


def from_history(points: list[PricePoint]) -> Hint | None:
    """Свои цены -> подсказка. Пусто -> None, и бот молчит.

    Молчание здесь — не отсутствие функции, а решение: строка без цены и так
    видна в предпросмотре с причиной, а «нет данных» на пустом месте только
    шумит.
    """
    if not points:
        return None

    fresh = max(points, key=lambda point: point.on)
    prices = [point.price for point in points]
    return Hint(
        last=fresh.price,
        on=fresh.on,
        times=len(points),
        unit_spoken=fresh.unit_spoken,
        median=median(prices) if len(prices) >= MIN_FOR_MEDIAN else None,
    )
