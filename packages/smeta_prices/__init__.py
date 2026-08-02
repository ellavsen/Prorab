"""smeta-prices — справочник позиций и подсказка цены.

Чистый пакет, как ядро: только stdlib и Decimal. Ни базы, ни сети, ни
Telegram. Цену он не придумывает — он умеет узнать позицию, сравнить единицы
и посчитать медиану по тому, что уже было (ADR-017).
"""

from .normalize import fold, normalize_name, packaging_form, same_unit
from .packaging import BASES, FORM_GROUPS, FORMS, FormCollision, build_forms
from .stats import (
    MIN_FOR_SPREAD,
    median,
    outlier_bounds,
    percentile_25,
    percentile_75,
    without_outliers,
)
from .suggest import MIN_FOR_MEDIAN, Hint, PricePoint, from_history

__all__ = [
    "BASES",
    "FORMS",
    "FORM_GROUPS",
    "MIN_FOR_MEDIAN",
    "MIN_FOR_SPREAD",
    "FormCollision",
    "Hint",
    "PricePoint",
    "build_forms",
    "fold",
    "from_history",
    "median",
    "normalize_name",
    "outlier_bounds",
    "packaging_form",
    "percentile_25",
    "percentile_75",
    "same_unit",
    "without_outliers",
]
