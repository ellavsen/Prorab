"""Сметы и состояние диалога. Состояние живёт в базе, а не в памяти процесса."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from smeta_core import EstimateStatus

from . import history
from .guards import require_draft
from .models import Estimate, Position, UserState, utcnow

RETENTION_LIMIT = 5  # хранить последние N смет на пользователя


def user_state(db: Session, uid: int) -> UserState:
    state = db.get(UserState, uid)
    if state is None:
        state = UserState(user_id=uid)
        db.add(state)
        db.commit()
    return state


def get_category(db: Session, uid: int) -> str | None:
    return user_state(db, uid).category


def set_category(db: Session, uid: int, category: str | None) -> None:
    user_state(db, uid).category = category
    db.commit()


DRAFT_FIELDS = (
    "draft_step", "draft_name", "draft_unit",
    "draft_qty_milli", "draft_price_kop", "pending_line",
)


def update_draft(db: Session, uid: int, **fields) -> UserState:
    """Запоминает шаг пошагового ввода. Хранится в базе, а не в памяти (ADR-010)."""
    state = user_state(db, uid)
    for name, value in fields.items():
        if name not in DRAFT_FIELDS:
            raise ValueError(f"неизвестное поле черновика: {name}")
        setattr(state, name, value)
    db.commit()
    return state


def clear_draft(db: Session, uid: int) -> None:
    state = user_state(db, uid)
    for name in DRAFT_FIELDS:
        setattr(state, name, None)
    db.commit()


def set_rates(db: Session, estimate: Estimate, work_bp: int, material_bp: int) -> None:
    """Ставка — часть документа, поэтому меняется только у этой сметы (ADR-003).

    Пересчитывать ничего не нужно: итоги считаются из позиций и ставок при
    каждом чтении, поэтому смена ставки видна сразу и только здесь. У
    отправленной сметы ставка не меняется вовсе: она уже в документе (И2).
    """
    require_draft(estimate)
    estimate.markup_work_bp = work_bp
    estimate.markup_material_bp = material_bp
    estimate.updated_at = utcnow()
    db.commit()


def next_estimate_number(db: Session, uid: int) -> int:
    highest = db.execute(
        select(func.max(Estimate.number)).where(Estimate.user_id == uid)
    ).scalar()
    return (highest or 0) + 1


def newest_estimate(db: Session, uid: int) -> Estimate | None:
    return db.execute(
        select(Estimate)
        .where(Estimate.user_id == uid)
        .order_by(Estimate.updated_at.desc(), Estimate.id.desc())
    ).scalars().first()


def create_estimate(db: Session, uid: int, name: str | None = None, **fields) -> Estimate:
    number = next_estimate_number(db, uid)
    estimate = Estimate(
        user_id=uid, number=number, name=name or f"Смета №{number}", **fields
    )
    db.add(estimate)
    db.commit()
    db.refresh(estimate)
    return estimate


def set_current_estimate(db: Session, uid: int, estimate_id: int) -> None:
    user_state(db, uid).current_estimate_id = estimate_id
    db.commit()


def current_estimate(db: Session, uid: int) -> Estimate:
    """Активная смета пользователя.

    Читается из user_state, поэтому переживает рестарт процесса. Раньше здесь
    был кэш в памяти, а при промахе — молчаливый переход на самую свежую смету:
    после рестарта позиции уходили не туда, куда пользователь переключился
    командой /switch, и он об этом не узнавал (ADR-005).
    """
    state = user_state(db, uid)
    if state.current_estimate_id is not None:
        estimate = db.get(Estimate, state.current_estimate_id)
        if estimate is not None and estimate.user_id == uid:
            return estimate

    # Сюда попадаем только при первом контакте или если смета была удалена.
    estimate = newest_estimate(db, uid) or create_estimate(db, uid)
    state.current_estimate_id = estimate.id
    db.commit()
    return estimate


def find_by_number(db: Session, uid: int, number: int) -> Estimate | None:
    """Действующая редакция номера, а не первая попавшаяся.

    До Sprint 7 у номера была ровно одна смета, и `.first()` без сортировки
    был честен. С версиями их несколько, и без ORDER BY /switch уводил на
    заменённую редакцию — молча, а следующая же позиция упиралась в охрану.
    """
    return db.execute(
        select(Estimate)
        .where(Estimate.user_id == uid, Estimate.number == number)
        .order_by(Estimate.version.desc())
    ).scalars().first()


def list_estimates(db: Session, uid: int, limit: int = RETENTION_LIMIT) -> list[Estimate]:
    return list(db.execute(
        select(Estimate)
        .where(Estimate.user_id == uid)
        .order_by(Estimate.updated_at.desc(), Estimate.id.desc())
        .limit(limit)
    ).scalars().all())


def touch_estimate(db: Session, estimate: Estimate) -> None:
    estimate.updated_at = utcnow()
    db.commit()


def enforce_retention(db: Session, uid: int) -> Estimate | None:
    """Оставляет последние RETENTION_LIMIT ЧЕРНОВИКОВ.

    Отправленное не удаляется никогда: по нему выставлен счёт, на него у
    заказчика ссылка, и исчезнуть оно не может из-за того, что автор начал
    шестую смету (ADR-019, money.md §1.4.4). Пятёрка всегда была про
    черновики — просто до Sprint 7 других состояний не существовало.

    Возвращает новую активную смету, если старая попала под удаление — вызывающий
    обязан сказать об этом пользователю, а не переключить его молча.
    """
    drafts = list(db.execute(
        select(Estimate)
        .where(Estimate.user_id == uid, Estimate.status == EstimateStatus.DRAFT)
        .order_by(Estimate.updated_at.desc(), Estimate.id.desc())
    ).scalars().all())
    if len(drafts) <= RETENTION_LIMIT:
        return None

    keep, drop = drafts[:RETENTION_LIMIT], drafts[RETENTION_LIMIT:]
    drop_ids = [e.id for e in drop]

    # Архив и удаление — одна транзакция. Это единственное место в проекте,
    # где данные исчезают безвозвратно: половина операции здесь означала бы
    # либо историю от несостоявшегося удаления, либо смету, стёртую без
    # сохранённых цен (ADR-017).
    try:
        history.archive(db, uid, drop_ids)
        history.prune(db, uid)
        _drop_estimates(db, uid, drop_ids)
        state = user_state(db, uid)
        switched = keep[0] if state.current_estimate_id in drop_ids else None
        if switched is not None:
            state.current_estimate_id = switched.id
        db.commit()
    except Exception:
        db.rollback()
        raise
    return switched


def _drop_estimates(db: Session, uid: int, drop_ids: list[int]) -> None:
    db.execute(delete(Position).where(
        Position.user_id == uid, Position.estimate_id.in_(drop_ids)
    ))
    db.execute(delete(Estimate).where(
        Estimate.user_id == uid, Estimate.id.in_(drop_ids)
    ))


def create_new_estimate_like(db: Session, uid: int, source: Estimate) -> Estimate:
    """Новая пустая смета с тем же названием и ставками, сразу активная.

    Ставки переносятся из исходной, а не берутся из настроек: «обновить смету»
    значит «то же самое, но заново».
    """
    estimate = create_estimate(
        db, uid, name=source.name,
        markup_work_bp=source.markup_work_bp,
        markup_material_bp=source.markup_material_bp,
    )
    set_current_estimate(db, uid, estimate.id)
    enforce_retention(db, uid)
    return estimate
