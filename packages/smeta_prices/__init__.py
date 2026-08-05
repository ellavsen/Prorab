"""smeta-prices — справочник позиций и подсказка цены.

Чистый пакет, как ядро: только stdlib и Decimal. Ни базы, ни сети, ни
Telegram. Цену он не придумывает — он умеет узнать позицию, сравнить единицы
и посчитать медиану по тому, что уже было (ADR-017).
"""

from .catalog import CATALOG, DAY_UNITS, Catalog, CatalogError, Item
from .match import FUZZY_CUTOFF, MAX_EXTRA_TOKENS, by_containment, by_typo, resolve
from .normalize import display_unit, fold, normalize_name, packaging_form, same_unit
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
    "CATALOG",
    "DAY_UNITS",
    "FORMS",
    "FORM_GROUPS",
    "FUZZY_CUTOFF",
    "MAX_EXTRA_TOKENS",
    "MIN_FOR_MEDIAN",
    "MIN_FOR_SPREAD",
    "Catalog",
    "CatalogError",
    "FormCollision",
    "Hint",
    "Item",
    "PricePoint",
    "build_forms",
    "by_containment",
    "by_typo",
    "display_unit",
    "fold",
    "from_history",
    "median",
    "normalize_name",
    "outlier_bounds",
    "packaging_form",
    "percentile_25",
    "percentile_75",
    "resolve",
    "same_unit",
    "without_outliers",
]
