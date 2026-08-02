"""DTO границы LLM. Вложенная схема, все значения — строки.

Вложенность нужна ровно за тем, чтобы отличать «не названо» от «ноль»:
плоская строка их путает, и `missing` тихо уезжает в расчёт как 0.

Значения — строки, а не JSON-числа. Число в JSON это double, и `1234.56`
пересекает границу двоичной дробью; ADR-008 запретил это для HTTP API, и на
границе LLM причина ровно та же.

Это **DTO границы, а не доменная модель**. После подтверждения человеком он
схлопывается в плоский PositionData и уходит в ядро; smeta-core про эту схему
не знает (ADR-012).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from smeta_core import (
    Category,
    PositionData,
    check_name,
    parse_price,
    parse_quantity,
    unit_decision,
)


class FieldStatus(StrEnum):
    STATED = "stated"      # названо явно
    APPROX = "approx"      # названо приблизительно: «мешков двадцать»
    MISSING = "missing"    # не названо вовсе


class PriceScope(StrEnum):
    PER_UNIT = "per_unit"  # «по семьсот» — за единицу
    TOTAL = "total"        # «на тридцать тысяч за всё» — за всё
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExtractionStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"        # позиций нет, но текст осмысленный
    GARBAGE = "garbage"    # мусор или попытка увести модель с задачи


# Категории в коде английские (конституция: русский только на экране).
_CATEGORIES = {"work": Category.WORK, "material": Category.MATERIAL}

# Единица строки, в которую схлопывается «за всё».
TOTAL_UNIT = "компл"


@dataclass(frozen=True)
class Quantity:
    """Количество. value пусто ровно тогда, когда status == missing."""

    status: str = FieldStatus.MISSING
    value: str = ""


@dataclass(frozen=True)
class Price:
    """Цена. scope отвечает на вопрос «по семьсот» — за штуку или за всё."""

    status: str = FieldStatus.MISSING
    scope: str = PriceScope.UNKNOWN
    value: str = ""


@dataclass(frozen=True)
class PositionCandidate:
    """Позиция, как её увидела модель.

    unit — канон из справочника ядра, "" если модель не уверена.
    unit_spoken — как сказал человек: «мешков», «квадратов». В документ
    заказчику печатается именно сказанное (ADR-015).
    """

    name: str
    qty: Quantity = field(default_factory=Quantity)
    price: Price = field(default_factory=Price)
    unit: str = ""
    unit_spoken: str = ""
    category: str = "unknown"
    source_quote: str = ""
    confidence: str = Confidence.MEDIUM


@dataclass(frozen=True)
class IgnoredFragment:
    """Что модель сознательно пропустила и почему."""

    quote: str
    reason: str


@dataclass(frozen=True)
class Extraction:
    status: str = ExtractionStatus.EMPTY
    positions: tuple[PositionCandidate, ...] = ()
    ignored: tuple[IgnoredFragment, ...] = ()


def pick_category(raw: str, fallback: Category) -> Category:
    """Категория от модели, а если она её не назвала — выбор человека."""
    return _CATEGORIES.get(str(raw).strip().lower(), fallback)


def to_position(candidate: PositionCandidate, fallback: Category) -> PositionData:
    """Кандидат -> позиция домена. ValueError, если модель вернула негодное."""
    if candidate.qty.status == FieldStatus.MISSING or not candidate.qty.value:
        raise ValueError("Количество: не названо")
    if candidate.price.status == FieldStatus.MISSING or not candidate.price.value:
        raise ValueError("Цена: не названа")

    return PositionData(
        category=pick_category(candidate.category, fallback),
        name=check_name(candidate.name),
        qty=parse_quantity(candidate.qty.value),
        price=parse_price(candidate.price.value),
        unit=unit_decision(candidate.unit, candidate.unit_spoken),
        unit_spoken=candidate.unit_spoken or candidate.unit,
    )
