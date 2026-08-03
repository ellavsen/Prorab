"""Состояние сметы и проверка целостности отправленной (money.md §1.3).

«Отправлено заказчику» значит «по этому выставлен счёт». Дальше документ не
меняется, а любая генерация документа по отправленной смете обязана сначала
убедиться, что данные те же самые: пересчитать и сверить с замороженным. Не
сошлось — документ не выдаётся вовсе. Ошибка целостности это не «немного
другая сумма», это «алгоритм или данные поменялись задним числом».

Сам формат слепка живёт в snapshot.py — он версионируется, а это модуль про
переходы и про отказ.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

from .calculate import calculate_estimate
from .models import EstimateTotals, PositionData
from .money import RateBase
from .snapshot import SNAPSHOT_FORMAT, frozen_hash


class EstimateStatus(StrEnum):
    """Значения английские: это код, а не экран (как Category)."""

    DRAFT = "draft"            # правится свободно
    SENT = "sent"              # отправлено заказчику, неизменяемо
    SUPERSEDED = "superseded"  # заменено следующей отправленной версией
    CANCELLED = "cancelled"    # отменено; мягкая пометка, не удаление


# Как статус называется человеку. Живёт рядом с самим статусом, потому что
# читателей теперь трое — бот, PDF и публичная страница, — и три копии этого
# словаря разошлись бы так же, как расходились четыре вычислителя до Sprint 1.
STATUS_LABEL = {
    EstimateStatus.DRAFT: "Черновик",
    EstimateStatus.SENT: "Отправлена заказчику",
    EstimateStatus.SUPERSEDED: "Заменена новой редакцией",
    EstimateStatus.CANCELLED: "Отменена",
}


class IntegrityError(ValueError):
    """Пересчёт разошёлся с замороженным. Документ не выдаётся."""


def check_integrity(
    positions: Sequence[PositionData],
    work_rate: Decimal,
    material_rate: Decimal,
    rate_base: RateBase = RateBase.COST,
    *,
    expected_hash: str,
    expected_total: Decimal,
    expected_format: int = SNAPSHOT_FORMAT,
) -> EstimateTotals:
    """Суммы отправленной сметы — или отказ. Промежуточного ответа нет.

    Возвращает пересчитанные итоги, чтобы у генератора документа не было
    второго источника чисел: он получает их отсюда же, вместе с проверкой.

    Единственное место в проекте, которому позволено сериализовать не текущим
    форматом: смету надо сверить с тем, чем её замораживали. Выписать по
    старому формату новый документ отсюда нельзя — эта функция ничего не
    записывает.
    """
    actual_hash = frozen_hash(
        positions, work_rate, material_rate, rate_base, snapshot_format=expected_format
    )
    if actual_hash != expected_hash:
        raise IntegrityError(
            "Смета изменилась после отправки: слепок не совпадает. Документ не выдан."
        )

    totals = calculate_estimate(positions, work_rate, material_rate, rate_base)
    if totals.total != expected_total:
        raise IntegrityError(
            f"Пересчёт отправленной сметы дал {totals.total}, "
            f"а заморожено было {expected_total}. Документ не выдан."
        )
    return totals
