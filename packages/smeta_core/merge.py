"""Слияние дублей. Одна реализация вместо двух разошедшихся."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from .models import PositionData
from .money import QTY_MAX, format_qty


def merge_duplicates(positions: Sequence[PositionData]) -> tuple[PositionData, ...]:
    """Складывает количества позиций с одинаковыми (категория, имя, цена).

    Порядок первого появления сохраняется. Слияние выполняется до расчёта,
    поэтому переполнение лимита ловится здесь, а не в арифметике.
    """
    merged: dict[tuple[str, str, str], PositionData] = {}
    order: list[tuple[str, str, str]] = []

    for position in positions:
        key = (str(position.category), position.name, str(position.price))
        previous = merged.get(key)
        if previous is None:
            merged[key] = position
            order.append(key)
            continue

        total_qty = previous.qty + position.qty
        if total_qty > QTY_MAX:
            raise ValueError(
                f"«{position.name}»: суммарное количество {format_qty(total_qty)} "
                f"превышает лимит {format_qty(QTY_MAX)}"
            )
        merged[key] = replace(previous, qty=total_qty)

    return tuple(merged[key] for key in order)
