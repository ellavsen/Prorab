"""Заморозка сметы: канонический слепок и проверка целостности (money.md §1.3).

«Отправлено заказчику» значит «по этому выставлен счёт». Дальше документ не
меняется, а любая генерация документа по отправленной смете обязана сначала
убедиться, что данные те же самые: пересчитать и сверить с замороженным. Не
сошлось — документ не выдаётся вовсе. Ошибка целостности это не «немного
другая сумма», это «алгоритм или данные поменялись задним числом».

Хеш считается по целым минорным единицам, а не по Decimal: `40.5` и `40.500`
— одно количество, и слепок обязан это знать. Порядок позиций в слепок входит:
документ упорядочен, и перестановка строк — тоже изменение документа.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

from .calculate import calculate_estimate
from .models import EstimateTotals, PositionData
from .money import to_bp, to_kop, to_milli


class EstimateStatus(StrEnum):
    """Значения английские: это код, а не экран (как Category)."""

    DRAFT = "draft"            # правится свободно
    SENT = "sent"              # отправлено заказчику, неизменяемо
    SUPERSEDED = "superseded"  # заменено следующей отправленной версией
    CANCELLED = "cancelled"    # отменено; мягкая пометка, не удаление


class IntegrityError(ValueError):
    """Пересчёт разошёлся с замороженным. Документ не выдаётся."""


def canonical_form(
    positions: Sequence[PositionData], work_rate: Decimal, material_rate: Decimal
) -> str:
    """Каноническая сериализация: одинаковая смета — одинаковая строка.

    JSON с сортированными ключами и без пробелов: расположение полей в коде и
    отступы на слепок не влияют, а копейка — влияет.
    """
    return json.dumps(
        {
            "rates": {"material": to_bp(material_rate), "work": to_bp(work_rate)},
            "positions": [
                {
                    "category": str(position.category),
                    "name": position.name,
                    "price_kop": to_kop(position.price),
                    "qty_milli": to_milli(position.qty),
                    "unit": position.unit,
                    "unit_spoken": position.unit_spoken,
                }
                for position in positions
            ],
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def frozen_hash(
    positions: Sequence[PositionData], work_rate: Decimal, material_rate: Decimal
) -> str:
    return hashlib.sha256(
        canonical_form(positions, work_rate, material_rate).encode("utf-8")
    ).hexdigest()


def check_integrity(
    positions: Sequence[PositionData],
    work_rate: Decimal,
    material_rate: Decimal,
    expected_hash: str,
    expected_total: Decimal,
) -> EstimateTotals:
    """Суммы отправленной сметы — или отказ. Промежуточного ответа нет.

    Возвращает пересчитанные итоги, чтобы у генератора документа не было
    второго источника чисел: он получает их отсюда же, вместе с проверкой.
    """
    actual_hash = frozen_hash(positions, work_rate, material_rate)
    if actual_hash != expected_hash:
        raise IntegrityError(
            "Смета изменилась после отправки: слепок не совпадает. Документ не выдан."
        )

    totals = calculate_estimate(positions, work_rate, material_rate)
    if totals.total != expected_total:
        raise IntegrityError(
            f"Пересчёт отправленной сметы дал {totals.total}, "
            f"а заморожено было {expected_total}. Документ не выдан."
        )
    return totals
