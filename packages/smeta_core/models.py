"""Доменные структуры. Неизменяемые, самовалидирующиеся, без зависимостей."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .money import check_price, check_quantity

NAME_MAX_LEN = 200


class Category(StrEnum):
    """Значения совпадают с тем, что лежит в БД и что видит пользователь.

    Именно StrEnum, а не (str, Enum): у второго str(Category.WORK) даёт
    "Category.WORK", и любое сравнение со строкой из базы тихо не срабатывает.
    """

    WORK = "Работа"
    MATERIAL = "Материал"


def check_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        raise ValueError("Наименование: пустое")
    if len(s) > NAME_MAX_LEN:
        raise ValueError(f"Наименование: не длиннее {NAME_MAX_LEN} символов")
    return s


@dataclass(frozen=True)
class PositionData:
    """Позиция сметы. Невалидной такой объект существовать не может."""

    category: Category
    name: str
    qty: Decimal
    price: Decimal
    unit: str = ""

    def __post_init__(self) -> None:
        check_name(self.name)
        check_quantity(self.qty)
        check_price(self.price)


@dataclass(frozen=True)
class LineTotal:
    """Одна строка расчёта. base — без наценки, total — с наценкой."""

    position: PositionData
    base: Decimal
    total: Decimal


@dataclass(frozen=True)
class EstimateTotals:
    """Результат calculate_estimate(). Единственный источник сумм для всех каналов."""

    lines: tuple[LineTotal, ...]
    subtotal: Decimal
    markup: Decimal
    total: Decimal
