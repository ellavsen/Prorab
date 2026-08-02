"""Схлопывание «за всё» в одну строку — вместо деления.

Человек сказал «на тридцать тысяч за всё». Заказчик обязан увидеть 30 000.
Деление на количество даёт 4285,71, а обратно — 29 999,97: три копейки
расхождения с тем, что было сказано. Показать это расхождение не значит его
исправить, поэтому мы не делим вовсе.

Количество не теряется: оно уходит в наименование, а строка получает
количество 1 и единицу «компл». Формула Excel при этом целая, новой доменной
сущности не нужно (ADR-012).
"""

from __future__ import annotations

from dataclasses import replace

from smeta_core import NAME_MAX_LEN

from .candidates import (
    TOTAL_UNIT,
    FieldStatus,
    PositionCandidate,
    Price,
    PriceScope,
    Quantity,
)


def counted_name(candidate: PositionCandidate) -> str:
    """«Покраска» + 100 квадратов -> «Покраска (100 квадратов)»."""
    spoken = candidate.unit_spoken or candidate.unit
    inner = " ".join(part for part in (candidate.qty.value, spoken) if part)
    if not inner:
        return candidate.name
    return f"{candidate.name} ({inner})"[:NAME_MAX_LEN]


def collapse_total_scope(candidate: PositionCandidate) -> PositionCandidate:
    """Строку с ценой «за всё» превращает в одну позицию-комплект."""
    if candidate.price.scope != PriceScope.TOTAL or not candidate.price.value:
        return candidate

    return replace(
        candidate,
        name=counted_name(candidate),
        qty=Quantity(status=FieldStatus.STATED, value="1"),
        unit=TOTAL_UNIT,
        unit_spoken=TOTAL_UNIT,
        price=Price(
            status=candidate.price.status,
            scope=PriceScope.PER_UNIT,
            value=candidate.price.value,
        ),
    )
