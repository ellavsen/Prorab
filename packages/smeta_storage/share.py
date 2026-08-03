"""Публичная ссылка: выдача, проверка, просмотр, согласование, отзыв.

Первый раз проект отдаёт данные наружу без аутентификации, поэтому весь вес
защиты лежит на самом токене: 32 байта из secrets, ничего не выведено ни из id
сметы, ни из владельца. Второго фактора нет намеренно — он превратил бы
«открыть ссылку» в «зарегистрироваться», а это ровно то, чего заказчик делать
не станет (ADR-020).

Отсюда же следует, что запись из публичного приложения ограничена двумя
фактами: отметкой просмотра и статусом согласования. Всё остальное — чтение.
Соответствие проверяется тестом архитектуры, а не обещанием.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from smeta_core import STATUS_LABEL, EstimateStatus, EstimateTotals

from .models import Estimate, ShareLink, utcnow
from .versions import StateError, verified_totals

# 32 байта — 256 бит энтропии, 43 символа в адресе. Перебор такого пространства
# не отличается от перебора приватного ключа; ограничивать частоту запросов
# ради него не нужно, и оракула для перебора страница не даёт (ADR-020).
TOKEN_BYTES = 32

# Сколько живёт ссылка, пока её не согласовали. Смета — предложение, а не
# вечный документ; неотвеченное предложение должно истекать само.
DEFAULT_TTL_DAYS = 30


@dataclass(frozen=True)
class SharedEstimate:
    """Всё, что видит человек со ссылкой. Больше на страницу не попадает ничего.

    Список закрыт и проверяется тестом: добавить сюда поле — это сознательное
    решение показать его постороннему, а не побочный эффект правки соседнего
    кода. Владельца, его id, номера телефона и истории цен здесь нет.

    Название сметы человек пишет сам, и в нём может оказаться фамилия
    заказчика или адрес объекта. Поэтому бот при выдаче ссылки предупреждает
    об этом прямым текстом — скрыть название нельзя, документ без названия
    не документ.
    """

    number: int
    version: int
    title: str
    on: date
    status: str
    work_rate: Decimal
    material_rate: Decimal
    # Без основания «6%» на странице двусмысленны: заказчик не различит
    # наценку сверху и удержание из выставленной суммы (ADR-024).
    rate_base: str
    totals: EstimateTotals
    approved_on: date | None


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(db: Session, estimate: Estimate, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    """Выдаёт ссылку на отправленную смету. Токен возвращается один раз.

    Черновик наружу не отдаётся: у него нет замороженных итогов, и то, что
    заказчик увидел бы сегодня, завтра поменялось бы без следа (money.md И3).

    У согласованной сметы срока нет: он снят один раз и навсегда, а не у
    конкретного адреса, поэтому перевыпуск ссылки его не возвращает.
    """
    if estimate.status == EstimateStatus.DRAFT:
        raise StateError("Ссылка выдаётся только на отправленную смету: /send")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    db.add(ShareLink(
        token_sha256=digest(token),
        estimate_id=estimate.id,
        expires_at=None if estimate.approved_at else utcnow() + timedelta(days=ttl_days),
    ))
    db.commit()
    return token


def reissue(db: Session, estimate: Estimate) -> str:
    """Отзывает действующую ссылку и выдаёт новую — одним шагом.

    Частый случай: заказчик потерял адрес, а у прораба его тоже нет — токен
    хранится отпечатком, показать повторно неоткуда (ADR-020). Отзыв и выдача
    здесь неразделимы намеренно: две живые ссылки на один документ означали
    бы, что «отозвал» не значит «закрыл».

    Согласование не теряется: оно на смете, а не на адресе.
    """
    live = latest_for(db, estimate.id)
    if live is not None and live.is_live:
        revoke(db, live)
    return issue(db, estimate)


def resolve(db: Session, token: str) -> ShareLink | None:
    """Живая ссылка или ничего.

    Причина отказа не возвращается намеренно: «отозвано» и «такого не было» —
    разные ответы только для того, кто перебирает токены.
    """
    link = db.execute(
        select(ShareLink).where(ShareLink.token_sha256 == digest(token))
    ).scalar_one_or_none()
    return link if link is not None and link.is_live else None


def latest_for(db: Session, estimate_id: int) -> ShareLink | None:
    """Последняя выданная ссылка на смету — для статуса в боте."""
    return db.execute(
        select(ShareLink)
        .where(ShareLink.estimate_id == estimate_id)
        .order_by(ShareLink.created_at.desc(), ShareLink.id.desc())
    ).scalars().first()


def mark_viewed(db: Session, link: ShareLink) -> None:
    """Два timestamp и ничего больше: ни адреса, ни браузера, ни счётчика."""
    now = utcnow()
    if link.first_viewed_at is None:
        link.first_viewed_at = now
    link.last_viewed_at = now
    db.commit()


def approve(db: Session, link: ShareLink) -> Estimate:
    """Согласовано — значит бессрочно, пока владелец не отозвал явно.

    Отметка ставится на смету: согласовывают документ, а не адрес, по которому
    его открыли. Иначе перевыпуск ссылки терял бы согласие заказчика, и его
    пришлось бы копировать со ссылки на ссылку — то есть завести второй
    источник истины про один и тот же факт (ADR-020).

    Срок снимается, а не продлевается: согласованный документ, исчезнувший
    через месяц, хуже отсутствующего — на него уже сослались.
    """
    estimate = _estimate_of(db, link)
    if estimate.approved_at is None:
        estimate.approved_at = utcnow()
        link.expires_at = None
        db.commit()
    return estimate


def revoke(db: Session, link: ShareLink) -> ShareLink:
    """Закрывает доступ. Повторный отзыв — не ошибка, время первого сохраняется."""
    if link.revoked_at is None:
        link.revoked_at = utcnow()
        db.commit()
    return link


def _estimate_of(db: Session, link: ShareLink) -> Estimate:
    estimate = db.get(Estimate, link.estimate_id)
    if estimate is None:
        raise StateError("Смета, на которую выдана ссылка, не найдена.")
    return estimate


def document(db: Session, link: ShareLink) -> SharedEstimate:
    """Собирает то, что увидит заказчик. Суммы — только после сверки со слепком.

    IntegrityError сюда не перехватывается: показать документ, разошедшийся с
    замороженным, нельзя, а решать, что ответить постороннему, — дело
    приложения, не хранилища.
    """
    estimate = _estimate_of(db, link)
    totals = verified_totals(db, estimate)
    sent_at = estimate.sent_at or estimate.created_at
    return SharedEstimate(
        number=estimate.number,
        version=estimate.version,
        title=estimate.name,
        on=sent_at.date(),
        status=STATUS_LABEL.get(estimate.status, ""),
        work_rate=estimate.markup_work_rate,
        material_rate=estimate.markup_material_rate,
        rate_base=estimate.rate_base,
        totals=totals,
        approved_on=_day(estimate.approved_at),
    )


def _day(moment: datetime | None) -> date | None:
    return None if moment is None else moment.date()
