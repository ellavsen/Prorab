"""Машина состояний сметы: отправка, ревизия, замена (money.md §1.3–1.4).

«Отправлено заказчику» = «по этому выставлен счёт». Дальше документ не
меняется никогда: правка после отправки — это новая версия, а не мутация
старой. Заказчик, открывший вчерашнюю ссылку, обязан увидеть вчерашний
документ, даже если прораб с тех пор всё переписал.

Здесь только переходы. Запрет менять неотправляемое живёт в guards.py и
вызывается всеми путями записи — хендлеров много, и проверку в каждом из них
однажды забудут.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from smeta_core import (
    SNAPSHOT_FORMAT,
    EstimateStatus,
    RateBase,
    calculate_estimate,
    check_integrity,
    frozen_hash,
    to_kop,
)

from .models import Estimate, Position, utcnow
from .positions import load


class StateError(ValueError):
    """Переход, которого нет в машине состояний."""


def _domain(db: Session, estimate: Estimate) -> list:
    return [row.to_domain() for row in load(db, estimate.user_id, estimate.id)]


def send(db: Session, estimate: Estimate) -> Estimate:
    """DRAFT -> SENT. Замораживает итоги и слепок в одной транзакции (И3).

    Повторная отправка — ошибка, а не тихий no-op: «отправить ещё раз» и
    «отправить изменённое» человек различает плохо, а документ уже ушёл.
    """
    if estimate.status != EstimateStatus.DRAFT:
        raise StateError(f"Смета уже не черновик: {estimate.status}. Отправить нельзя.")

    positions = _domain(db, estimate)
    if not positions:
        raise StateError("В смете нет позиций — отправлять нечего.")

    # Основание ставки и версия формата станут колонками сметы следующим
    # шагом. Пока их нет, другого значения у сметы быть и не может: хранить
    # основание негде, а форматов в проекте один — тот, которым замораживают.
    totals = calculate_estimate(
        positions, estimate.markup_work_rate, estimate.markup_material_rate, RateBase.COST
    )
    try:
        estimate.status = EstimateStatus.SENT
        estimate.sent_at = utcnow()
        estimate.frozen_subtotal_kop = to_kop(totals.subtotal)
        estimate.frozen_markup_kop = to_kop(totals.markup)
        estimate.frozen_total_kop = to_kop(totals.total)
        estimate.frozen_hash = frozen_hash(
            positions,
            estimate.markup_work_rate,
            estimate.markup_material_rate,
            RateBase.COST,
        )
        _supersede_previous(db, estimate)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return estimate


def _supersede_previous(db: Session, estimate: Estimate) -> None:
    """Предыдущая версия уходит в SUPERSEDED только сейчас.

    Пока новая версия — черновик, действующей для заказчика остаётся старая:
    иначе правка «на пробу» обесценила бы документ, который у него на руках.
    """
    previous = estimate.supersedes_id and db.get(Estimate, estimate.supersedes_id)
    if previous is not None and previous.status == EstimateStatus.SENT:
        previous.status = EstimateStatus.SUPERSEDED


def revise(db: Session, estimate: Estimate) -> Estimate:
    """SENT -> новая версия DRAFT с копией позиций и ставок.

    Черновик правится напрямую, поэтому revise(DRAFT) — ошибка: она создала бы
    вторую версию там, где хватает обычной правки.
    """
    if estimate.status != EstimateStatus.SENT:
        raise StateError(
            f"Ревизия делается только с отправленной сметы, а эта — {estimate.status}."
        )

    revision = Estimate(
        user_id=estimate.user_id,
        number=estimate.number,
        version=estimate.version + 1,
        supersedes_id=estimate.id,
        name=estimate.name,
        status=EstimateStatus.DRAFT,
        markup_work_bp=estimate.markup_work_bp,
        markup_material_bp=estimate.markup_material_bp,
    )
    db.add(revision)
    db.flush()

    for row in load(db, estimate.user_id, estimate.id):
        position = row.to_domain()
        db.add(Position(
            user_id=estimate.user_id,
            estimate_id=revision.id,
            category=position.category.value,
            name=position.name,
            unit=position.unit,
            unit_spoken=position.unit_spoken,
            qty_milli=row.qty_milli,
            price_kop=row.price_kop,
        ))
    db.commit()
    db.refresh(revision)
    return revision


def cancel(db: Session, estimate: Estimate) -> Estimate:
    """Мягкая пометка. Версии не удаляются никогда (money.md §1.4.4)."""
    if estimate.status == EstimateStatus.CANCELLED:
        return estimate
    estimate.status = EstimateStatus.CANCELLED
    db.commit()
    return estimate


def verified_totals(db: Session, estimate: Estimate):
    """Суммы для документа. У отправленной — только после сверки со слепком.

    Черновик считается как считался: у него нет замороженного, с чем сверять,
    и меняться ему пока можно.
    """
    positions = _domain(db, estimate)
    if estimate.status == EstimateStatus.DRAFT or estimate.frozen_hash is None:
        return calculate_estimate(
            positions,
            estimate.markup_work_rate,
            estimate.markup_material_rate,
            RateBase.COST,
        )
    return check_integrity(
        positions,
        estimate.markup_work_rate,
        estimate.markup_material_rate,
        RateBase.COST,
        expected_hash=estimate.frozen_hash,
        expected_total=estimate.frozen_total,
        expected_format=SNAPSHOT_FORMAT,
    )


def history_of(db: Session, uid: int, number: int) -> list[Estimate]:
    """Все версии одного номера, от первой к последней."""
    return list(db.execute(
        select(Estimate)
        .where(Estimate.user_id == uid, Estimate.number == number)
        .order_by(Estimate.version)
    ).scalars().all())

