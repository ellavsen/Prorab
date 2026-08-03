"""Сравнение двух версий сметы: что добавилось, что ушло, что подорожало.

Только сравнение — ни одного умножения и ни одной суммы. Числа для показа
берутся из calculate_estimate, как и везде (ADR-002).

Позиции сопоставляются по паре (категория, наименование): именно так человек
понимает «та же позиция». Изменение количества и цены — это изменение, а не
удаление со вставкой.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from .models import PositionData


@dataclass(frozen=True)
class Change:
    """Позиция, которая была в обеих версиях, но изменилась."""

    before: PositionData
    after: PositionData

    @property
    def price_delta(self) -> Decimal:
        return self.after.price - self.before.price

    @property
    def qty_delta(self) -> Decimal:
        return self.after.qty - self.before.qty


@dataclass(frozen=True)
class VersionDiff:
    added: tuple[PositionData, ...] = ()
    removed: tuple[PositionData, ...] = ()
    changed: tuple[Change, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _key(position: PositionData) -> tuple[str, str]:
    return (str(position.category), position.name.strip().lower())


def diff_positions(
    before: Sequence[PositionData], after: Sequence[PositionData]
) -> VersionDiff:
    """Что изменилось между версиями. Порядок ответа — порядок новой версии.

    Дубли одного наименования схлопываются при вводе (money.md §5), поэтому
    здесь пара (категория, имя) уникальна; если вдруг нет — побеждает первая,
    и это лучше, чем показать половину изменений дважды.
    """
    old = {}
    for position in before:
        old.setdefault(_key(position), position)
    new = {}
    for position in after:
        new.setdefault(_key(position), position)

    added = tuple(position for key, position in new.items() if key not in old)
    removed = tuple(position for key, position in old.items() if key not in new)
    changed = tuple(
        Change(before=old[key], after=position)
        for key, position in new.items()
        if key in old and (old[key].price != position.price or old[key].qty != position.qty)
    )
    return VersionDiff(added=added, removed=removed, changed=changed)
