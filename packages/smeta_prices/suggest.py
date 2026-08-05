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
    """Что показать. Кнопка по умолчанию — last: ближе к сегодняшнему поставщику.

    low и high — минимум и максимум по выборке, и порога у них нет намеренно.
    Порог нужен вычисленному числу: квартиль на трёх точках считается по одной
    и лжёт (ADR-018). Эти два — не вычислены, а наблюдены: каждое человек
    называл сам, и показать их можно с двух точек.

    Без них история 450 / 700 / 1100 отвечала «1100» и выдавала за знание
    последнюю цену — ровно то, против чего написан ADR-017.

    last пустой, когда самый свежий день несёт несколько несогласных цен: в
    истории нет времени точнее дня, и какая из них последняя — неизвестно.
    Тогда не показывается ни слово «последняя», ни кнопка с ней: скрыть
    утверждение, оставив действующей кнопку, значило бы убрать неправду с
    экрана, не убрав её из поведения (ADR-026).
    """

    last: Decimal | None
    on: date
    times: int
    low: Decimal
    high: Decimal
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
    newest = {point.price for point in points if point.on == fresh.on}
    prices = [point.price for point in points]
    return Hint(
        # Одна цена в самый свежий день — она и последняя. Несколько
        # одинаковых — тоже: какую из них ни возьми, число то же самое.
        last=newest.pop() if len(newest) == 1 else None,
        on=fresh.on,
        times=len(points),
        low=min(prices),
        high=max(prices),
        unit_spoken=fresh.unit_spoken,
        median=median(prices) if len(prices) >= MIN_FOR_MEDIAN else None,
    )
