"""Позиции сметы. Границей Decimal <-> целые копейки является этот модуль."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from smeta_core import (
    Category,
    EstimateTotals,
    PositionData,
    calculate_estimate,
    merge_duplicates,
    to_kop,
    to_milli,
)

from .models import Estimate, Position


def load(db: Session, uid: int, estimate_id: int) -> list[Position]:
    return list(db.execute(
        select(Position)
        .where(Position.user_id == uid, Position.estimate_id == estimate_id)
        .order_by(Position.category, Position.id)
    ).scalars().all())


def totals(db: Session, uid: int, estimate: Estimate) -> EstimateTotals:
    """Единственный способ узнать сумму сметы — один и тот же во всех каналах."""
    rows = load(db, uid, estimate.id)
    return calculate_estimate(
        [r.to_domain() for r in rows],
        estimate.markup_work_rate,
        estimate.markup_material_rate,
    )


def by_category(
    db: Session, uid: int, estimate_id: int
) -> tuple[list[PositionData], list[PositionData]]:
    """Позиции, разложенные по категориям: (материалы, работы).

    Слияния дублей здесь нет намеренно. Оно меняет итог — round2(q1*p) +
    round2(q2*p) не равно round2((q1+q2)*p) — поэтому склейка выполняется один
    раз при вводе, до расчёта (money.md §5). Если склеивать ещё и здесь, XLSX
    начнёт расходиться с /list ровно так, как расходился до Sprint 1.
    """
    domain = [r.to_domain() for r in load(db, uid, estimate_id)]
    return (
        [p for p in domain if p.category == Category.MATERIAL],
        [p for p in domain if p.category == Category.WORK],
    )


def find_twin(
    db: Session,
    uid: int,
    estimate_id: int,
    position: PositionData,
    exclude_id: int | None = None,
) -> Position | None:
    """Существующая позиция с теми же категорией, наименованием и ценой."""
    query = select(Position).where(
        Position.user_id == uid,
        Position.estimate_id == estimate_id,
        Position.category == position.category.value,
        Position.name == position.name,
        Position.price_kop == to_kop(position.price),
    )
    if exclude_id is not None:
        query = query.where(Position.id != exclude_id)
    return db.execute(query).scalars().first()


def add(db: Session, uid: int, estimate_id: int, position: PositionData) -> Position:
    """Добавляет позицию, складывая количество с дублем, если он есть.

    Склейка происходит здесь, до всякого округления — это единственное место,
    где она допустима.
    """
    twin = find_twin(db, uid, estimate_id, position)
    if twin is not None:
        merged = merge_duplicates([twin.to_domain(), position])[0]
        twin.qty_milli = to_milli(merged.qty)
        if not twin.unit:
            twin.unit = position.unit
        if not twin.unit_spoken:
            twin.unit_spoken = position.unit_spoken
        return twin

    row = Position(
        user_id=uid,
        estimate_id=estimate_id,
        category=position.category.value,
        name=position.name,
        unit=position.unit,
        unit_spoken=position.unit_spoken,
        qty_milli=to_milli(position.qty),
        price_kop=to_kop(position.price),
    )
    db.add(row)
    return row


def get(db: Session, uid: int, estimate_id: int, position_id: int) -> Position | None:
    return db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.user_id == uid,
            Position.estimate_id == estimate_id,
        )
    ).scalars().first()


def clear(db: Session, uid: int, estimate_id: int) -> None:
    db.execute(delete(Position).where(
        Position.user_id == uid, Position.estimate_id == estimate_id
    ))
