"""Запрет менять смету после отправки. Защита в глубину (money.md И2/И4).

Проверка живёт здесь, а не в хендлерах, по одной причине: хендлеров тринадцать,
путей записи ещё больше, и однажды кто-нибудь добавит четырнадцатый без
проверки. Единственный способ не забыть — сделать так, чтобы забыть было
негде: запись идёт через функции этого пакета, а они спрашивают разрешения
здесь.

«Отправлено заказчику» значит «по этому выставлен счёт». Тихое изменение
такого документа — не баг интерфейса, а подлог.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from smeta_core import EstimateStatus

from .models import Estimate

# Что человеку делать, когда он упёрся в запрет. Без этого сообщение
# «смета отправлена» выглядит поломкой, а не правилом.
FROZEN_HINT = "Отправленная смета не меняется. Сделай ревизию: /revise"

_LABELS = {
    EstimateStatus.SENT: "отправлена заказчику",
    EstimateStatus.SUPERSEDED: "заменена новой версией",
    EstimateStatus.CANCELLED: "отменена",
}


class FrozenEstimateError(ValueError):
    """Попытка изменить смету, которую менять нельзя."""


def require_draft(estimate: Estimate | None) -> Estimate:
    """Пропускает только черновик. Всё остальное — отказ с причиной."""
    if estimate is None:
        raise FrozenEstimateError("Смета не найдена.")
    if estimate.status == EstimateStatus.DRAFT:
        return estimate
    label = _LABELS.get(estimate.status, estimate.status)
    raise FrozenEstimateError(
        f"Смета №{estimate.number} (ред. {estimate.version}) {label}. {FROZEN_HINT}"
    )


def require_draft_by_id(db: Session, uid: int, estimate_id: int) -> Estimate:
    """То же, но по идентификатору: у путей записи под рукой обычно он."""
    estimate = db.get(Estimate, estimate_id)
    if estimate is None or estimate.user_id != uid:
        raise FrozenEstimateError("Смета не найдена.")
    return require_draft(estimate)
