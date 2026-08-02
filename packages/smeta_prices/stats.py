"""Медиана, перцентили и границы выброса. Только Decimal.

Перцентили считаются методом ближайшего ранга, без интерполяции. Это не вкус:
интерполяция синтезирует цену, которой никто не называл, а мы показываем
прорабу диапазон как «вот такие цены бывают». Каждое опубликованное число
обязано быть реально наблюдённым.

Медиана при чётном n — исключение: там среднее двух средних, округлённое до
копейки, иначе «медиана» зависела бы от того, какую из двух середин выбрали.
"""

from __future__ import annotations

from decimal import Decimal

from smeta_core import round2

# Классический множитель Тьюки — полтора межквартильных размаха. Записан как
# «размах плюс его половина»: float в денежный путь не попадает, умножения нет.
HALF = 2

# Ниже этого числа значений квартили считаются по одной-двум точкам, и разброс
# перестаёт быть разбросом (ADR-018).
MIN_FOR_SPREAD = 8


def median(values: list[Decimal]) -> Decimal:
    """Медиана. Чётное n — среднее двух середин, округлённое до копейки."""
    if not values:
        raise ValueError("медиана пустого множества не определена")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round2((ordered[middle - 1] + ordered[middle]) / 2)


def percentile_25(values: list[Decimal]) -> Decimal:
    """Ближайший ранг: ceil(n/4)-е значение по возрастанию."""
    ordered = sorted(values)
    rank = -(-len(ordered) // 4)
    return ordered[max(rank, 1) - 1]


def percentile_75(values: list[Decimal]) -> Decimal:
    """Ближайший ранг: ceil(3n/4)-е значение.

    Считается как n - floor(n/4) — это то же число, но без умножения, а
    умножение в проекте живёт только в калькуляторе (ADR-002).
    """
    ordered = sorted(values)
    rank = len(ordered) - len(ordered) // 4
    return ordered[max(rank, 1) - 1]


def outlier_bounds(values: list[Decimal]) -> tuple[Decimal, Decimal]:
    """Границы Тьюки [Q1 − 1.5·IQR, Q3 + 1.5·IQR].

    В выдачу 6a не проведены: своя история — не рынок, отсеивать в ней некого
    и не от кого. Понадобятся, когда появятся чужие факты (Sprint 6b).
    """
    if len(values) < MIN_FOR_SPREAD:
        raise ValueError(f"границы выброса требуют {MIN_FOR_SPREAD} значений")
    low, high = percentile_25(values), percentile_75(values)
    spread = high - low
    reach = spread + spread / HALF
    return round2(low - reach), round2(high + reach)


def without_outliers(values: list[Decimal]) -> list[Decimal]:
    """Значения внутри границ Тьюки. Мало данных — возвращает как есть."""
    if len(values) < MIN_FOR_SPREAD:
        return list(values)
    low, high = outlier_bounds(values)
    return [value for value in values if low <= value <= high]
