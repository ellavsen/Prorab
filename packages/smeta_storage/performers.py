"""Исполнитель: липкое значение и простановка на несколько строк сразу.

Поле включается употреблением, а не настройкой. Прораб, у которого исполнитель
стоит у каждой строки, не станет диктовать имя в каждой фразе, — но и
настроечного экрана заводить незачем: липкое значение помнит, кого он назвал
последним, и предпросмотр показывает его перед каждым подтверждением.

Липкость опасна невидимостью, и лечится она здесь двумя способами сразу:
она видна в каждом предпросмотре и протухает от простоя. Окно скользящее —
обновляется при каждом употреблении, а не при установке: исполнитель,
отвалившийся посреди рабочего дня, хуже прилипшего (ADR-028).

Запись сюда разрешена и у отправленной сметы. Это не дыра в защите заморозки,
а её граница: исполнитель в слепок не входит, документа заказчику не меняет и
итога не двигает. Прораб переставляет людей на объекте, не переиздавая смету.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Position, utcnow
from .repo import user_state

# Сколько живёт липкий исполнитель без употребления. Гипотеза, а не замер
# (ADR-018): обед переживает, ночь — нет.
STICKY_HOURS = 4


def sticky(db: Session, uid: int) -> str:
    """Кого проставлять следующей пачке. Протух — пусто, и молча."""
    state = user_state(db, uid)
    if not state.current_performer or state.performer_touched_at is None:
        return ""
    if utcnow() - state.performer_touched_at > timedelta(hours=STICKY_HOURS):
        return ""
    return state.current_performer


def remember(db: Session, uid: int, name: str) -> None:
    """Запоминает исполнителя и заводит отсчёт заново."""
    state = user_state(db, uid)
    state.current_performer = name or None
    state.performer_touched_at = utcnow() if name else None
    db.commit()


def forget_sticky(db: Session, uid: int) -> None:
    remember(db, uid, "")


def touch(db: Session, uid: int) -> None:
    """Продлевает липкость: окно считается от употребления, а не от установки."""
    state = user_state(db, uid)
    if state.current_performer:
        state.performer_touched_at = utcnow()
        db.commit()


def assign(
    db: Session, uid: int, estimate_id: int, name: str, ids: list[int] | None = None
) -> int:
    """Ставит исполнителя на строки сметы. Возвращает, скольким поставил.

    Без списка идентификаторов — всем строкам, у которых исполнителя ещё нет.
    Уже названного не перебивает: массовая простановка обязана быть безопасной
    для того, что человек проставил руками.

    Со списком — ровно этим строкам, и там уже перебивает: их назвали
    поимённо, значит, это и есть намерение.
    """
    query = select(Position).where(
        Position.user_id == uid, Position.estimate_id == estimate_id
    )
    if ids is not None:
        query = query.where(Position.id.in_(ids))
    else:
        query = query.where(Position.performer == "")

    rows = db.execute(query).scalars().all()
    for row in rows:
        row.performer = name
    db.commit()
    return len(rows)


def names(db: Session, uid: int, limit: int = 5) -> list[str]:
    """Кого этот прораб уже называл, свежие первыми.

    Словарь имён у него свой и крошечный — пять-пятнадцать человек, — поэтому
    список берётся целиком из его же строк. Сводить похожие имена мы не
    беремся: «Саня» и «Саша» могут быть одним человеком, а могут двумя, и
    ошибка здесь дороже удобства (ADR-028).
    """
    rows = db.execute(
        select(Position.performer, Position.id)
        .where(Position.user_id == uid, Position.performer != "")
        .order_by(Position.id.desc())
    ).all()
    seen: list[str] = []
    for performer, _ in rows:
        if performer not in seen:
            seen.append(performer)
        if len(seen) == limit:
            break
    return seen
