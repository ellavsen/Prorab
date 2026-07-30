"""Разбор пользовательского ввода в позицию сметы.

Формат строки: «Наименование, количество, цена».
Количество может нести единицу измерения: «150 м2».
"""

from __future__ import annotations

import re

from .models import Category, PositionData, check_name
from .money import parse_price, parse_quantity
from .units import normalize_unit

# Число, затем необязательный хвост-единица: «150 м2», «1.5», «2 шт».
_QTY_WITH_UNIT = re.compile(r"^(?P<num>[\d\s.,]*\d)\s*(?P<unit>.*)$")

_FORMAT_HINT = (
    "Ожидается три поля через запятую: Наименование, количество, цена.\n"
    "Дробные числа пиши через точку: 150.5 — запятая разделяет поля."
)


def split_qty_unit(raw: str) -> tuple[str, str]:
    """«150 м2» -> ("150", "м²"). Неизвестная единица отбрасывается."""
    match = _QTY_WITH_UNIT.match(raw.strip())
    if not match:
        return raw.strip(), ""
    return match.group("num"), normalize_unit(match.group("unit"))


def parse_position_line(line: str, category: Category) -> PositionData:
    """Разбирает одну строку ввода. Любая проблема — ValueError с текстом для пользователя."""
    parts = [part.strip() for part in (line or "").split(",")]
    if len(parts) != 3:
        raise ValueError(
            f"получено полей: {len(parts)}, а нужно 3.\n{_FORMAT_HINT}"
        )

    name = check_name(parts[0])
    qty_raw, unit = split_qty_unit(parts[1])
    return PositionData(
        category=category,
        name=name,
        qty=parse_quantity(qty_raw),
        price=parse_price(parts[2]),
        unit=unit,
    )
