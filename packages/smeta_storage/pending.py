"""Предпросмотр пачки: то, что распознала модель, до подтверждения человеком.

Хранилище здесь ничего не решает. Оно кладёт строки, как их отдали, и отдаёт
обратно. Годится строка или нет — вопрос домена, и ответ на него приходит
сюда уже готовым, в поле problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import PendingPosition


@dataclass(frozen=True)
class PendingRow:
    """Одна строка предпросмотра, как её вернула модель.

    total_price/total_qty заполняются только у строк, схлопнутых из «за всё»:
    по ним кнопка «Разбить на позиции» знает, что делить и на сколько.
    """

    category: str
    name: str
    qty: str
    price: str
    unit: str = ""
    unit_spoken: str = ""
    price_scope: str = "per_unit"
    total_price: str | None = None
    total_qty: str | None = None
    total_unit: str | None = None
    problem: str | None = None
    # Что человек сам платил за это раньше. Предложение, а не подстановка:
    # цена появится в строке только по нажатию (ADR-017).
    hint_price: str | None = None
    hint_median: str | None = None
    hint_low: str | None = None
    hint_high: str | None = None
    hint_matched_name: str | None = None
    # Кто делает эту строку. Приходит с границы ввода или проставляется
    # липким исполнителем, и в обоих случаях виден в предпросмотре (ADR-028).
    performer: str = ""
    hint_on: date | None = None
    hint_times: int | None = None


def replace(db: Session, uid: int, estimate_id: int, rows: list[PendingRow]) -> None:
    """Новое распознавание вытесняет предыдущее: двух предпросмотров не бывает."""
    clear(db, uid)
    for ordinal, row in enumerate(rows, start=1):
        db.add(PendingPosition(
            user_id=uid,
            estimate_id=estimate_id,
            ordinal=ordinal,
            category=row.category,
            name=row.name[:255],
            unit=row.unit[:32],
            unit_spoken=row.unit_spoken[:64],
            price_scope=row.price_scope,
            qty=row.qty[:32],
            price=row.price[:32],
            total_price=row.total_price,
            total_qty=row.total_qty,
            total_unit=row.total_unit,
            problem=None if row.problem is None else row.problem[:200],
            hint_price=row.hint_price,
            hint_median=row.hint_median,
            hint_low=row.hint_low,
            hint_high=row.hint_high,
            hint_matched_name=row.hint_matched_name,
            performer=row.performer,
            hint_on=row.hint_on,
            hint_times=row.hint_times,
        ))
    db.commit()


def load(db: Session, uid: int) -> list[PendingPosition]:
    return list(db.execute(
        select(PendingPosition)
        .where(PendingPosition.user_id == uid)
        .order_by(PendingPosition.ordinal)
    ).scalars().all())


def get(db: Session, uid: int, ordinal: int) -> PendingPosition | None:
    return db.execute(
        select(PendingPosition).where(
            PendingPosition.user_id == uid, PendingPosition.ordinal == ordinal
        )
    ).scalars().first()


def drop(db: Session, uid: int, ordinal: int) -> bool:
    """Убирает строку из предпросмотра. Нумерация остальных не меняется.

    Перенумеровать значило бы поменять подписи на кнопках у человека под
    пальцами: он метил в четвёртую, а попал бы в бывшую пятую.
    """
    row = get(db, uid, ordinal)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def clear(db: Session, uid: int) -> None:
    db.execute(delete(PendingPosition).where(PendingPosition.user_id == uid))
    db.commit()
