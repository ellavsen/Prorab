"""История своих цен: архив вытесненных смет и выборка для подсказки.

Ретеншен — единственное место в проекте, где данные исчезают безвозвратно.
Перед удалением сметы её позиции переписываются сюда: документ уходит, знание
о ценах остаётся (ADR-017).

Окно 180 дней применяется к ОБОИМ источникам — и к архиву, и к живым
позициям. Пять смет могут покрывать два года, поэтому без окна подсказка
«вы брали по 380» опиралась бы на позапрошлогоднюю цену, а формулировка
«за полгода» была бы неправдой (ADR-018).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from smeta_prices import PricePoint, normalize_name, packaging_form, same_unit

from .models import Position, PriceHistory, utcnow

# Окно истории. Число — гипотеза, а не измерение (ADR-018).
WINDOW_DAYS = 180


def _today() -> date:
    return utcnow().date()


def _cutoff(today: date | None) -> date:
    return (today or _today()) - timedelta(days=WINDOW_DAYS)


def _spoken(position: Position) -> str:
    """Сказанная единица в приведённой форме: «мешков» и «мешок» — одно."""
    return packaging_form(position.unit_spoken) or position.unit_spoken or ""


def _key(row) -> tuple:
    return (row.user_id, row.name_norm, row.unit, row.unit_spoken, row.observed_on)


def archive(db: Session, uid: int, estimate_ids: list[int]) -> int:
    """Переписывает позиции удаляемых смет в историю. Не коммитит.

    Дедупликация по (пользователь, имя, единица, день): повтор в тот же день
    не плодит строк. Внутри пачки побеждает последняя запись дня — она ближе
    к тому, чем сделка кончилась.
    """
    if not estimate_ids:
        return 0

    positions = db.execute(
        select(Position)
        .where(Position.user_id == uid, Position.estimate_id.in_(estimate_ids))
        .order_by(Position.id)
    ).scalars().all()

    fresh: dict[tuple, PriceHistory] = {}
    for position in positions:
        row = PriceHistory(
            user_id=uid,
            name_norm=normalize_name(position.name),
            unit=position.unit or "",
            unit_spoken=_spoken(position),
            price_kop=position.price_kop,
            observed_on=position.created_at.date(),
        )
        fresh[_key(row)] = row

    known = {
        _key(row) for row in db.execute(
            select(PriceHistory).where(PriceHistory.user_id == uid)
        ).scalars().all()
    }
    added = [row for key, row in fresh.items() if key not in known]
    db.add_all(added)
    return len(added)


def prune(db: Session, uid: int, today: date | None = None) -> int:
    """Свой ретеншен истории: старше окна — удалить. Не коммитит."""
    result = db.execute(delete(PriceHistory).where(
        PriceHistory.user_id == uid, PriceHistory.observed_on < _cutoff(today)
    ))
    return result.rowcount or 0


def forget(db: Session, uid: int) -> int:
    """Стирает историю пользователя целиком.

    Команды «удалить все мои данные» в боте пока нет (docs/known-issues.md).
    Когда появится, ей будет что вызвать — иначе история переживёт удаление
    пользователя, а это ровно то, чего быть не должно.
    """
    result = db.execute(delete(PriceHistory).where(PriceHistory.user_id == uid))
    return result.rowcount or 0


def lookup(
    db: Session, uid: int, name: str, unit: str, unit_spoken: str,
    today: date | None = None,
) -> list[PricePoint]:
    """Свои цены на эту позицию за окно, свежие первыми.

    Только свои: user_id стоит в обоих запросах, и пересечение историй разных
    пользователей — это уже краудсорсинг, то есть Sprint 6b.

    Единица сверяется, а не игнорируется: цена за м² и цена за м.п. — разные
    величины, и подставлять одну вместо другой нельзя (ADR-015).
    """
    key = normalize_name(name)
    if not key:
        return []

    cutoff = _cutoff(today)
    points: list[PricePoint] = []

    live = db.execute(
        select(Position).where(Position.user_id == uid, Position.name != "")
    ).scalars().all()
    for position in live:
        if position.created_at.date() < cutoff or normalize_name(position.name) != key:
            continue
        if not same_unit(unit, unit_spoken, position.unit or "", _spoken(position)):
            continue
        points.append(PricePoint(
            price=position.price, on=position.created_at.date(), unit_spoken=_spoken(position)
        ))

    archived = db.execute(
        select(PriceHistory).where(
            PriceHistory.user_id == uid,
            PriceHistory.name_norm == key,
            PriceHistory.observed_on >= cutoff,
        )
    ).scalars().all()
    for row in archived:
        if same_unit(unit, unit_spoken, row.unit, row.unit_spoken):
            points.append(PricePoint(price=row.price, on=row.observed_on,
                                     unit_spoken=row.unit_spoken))

    return sorted(points, key=lambda point: point.on, reverse=True)
