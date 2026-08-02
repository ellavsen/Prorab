"""smeta-prices — справочник позиций и подсказка цены.

Чистый пакет, как ядро: только stdlib и Decimal. Ни базы, ни сети, ни
Telegram. Цену он не придумывает — он умеет узнать позицию, сравнить единицы
и посчитать медиану по тому, что уже было (ADR-017).
"""

from .normalize import fold, normalize_name, packaging_form, same_unit
from .packaging import BASES, FORM_GROUPS, FORMS, FormCollision, build_forms

__all__ = [
    "BASES",
    "FORMS",
    "FORM_GROUPS",
    "FormCollision",
    "build_forms",
    "fold",
    "normalize_name",
    "packaging_form",
    "same_unit",
]
