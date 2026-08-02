"""Группа I: история своих цен (ADR-017, ADR-018).

Ретеншен — единственное место в проекте, где данные исчезают безвозвратно.
Поэтому тут проверяется не только «цена сохранилась», но и то, что половины
операции не бывает: либо архив и удаление вместе, либо ничего.
"""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from conftest import open_storage
from smeta_core import Category, PositionData
from smeta_storage import (
    RETENTION_LIMIT,
    PriceHistory,
    create_estimate,
    enforce_retention,
    history,
    positions,
    repo,
    utcnow,
)

UID, OTHER = 42, 77


def cement(price="380", unit="", unit_spoken="мешок", name="Цемент М500"):
    return PositionData(
        category=Category.MATERIAL, name=name, qty=D("20"), price=D(price),
        unit=unit, unit_spoken=unit_spoken,
    )


def fill(db, uid, count, position=None):
    """count смет с одной позицией в каждой."""
    for number in range(count):
        estimate = create_estimate(db, uid, name=f"Смета {number}")
        positions.add(db, uid, estimate.id, position or cement())
    db.commit()


def stored(db, uid=UID):
    return list(db.execute(
        select(PriceHistory).where(PriceHistory.user_id == uid)
    ).scalars().all())


# --- Ретеншен переносит цены, а не теряет их ---


def test_prices_survive_the_estimate_that_carried_them(tmp_path):
    """Документ уходит по ретеншену, знание о цене остаётся (ADR-017)."""
    _, Session = open_storage(tmp_path / "history.db")
    with Session() as db:
        fill(db, UID, RETENTION_LIMIT + 1)
        enforce_retention(db, UID)

        assert len(stored(db)) == 1
        found = history.lookup(db, UID, "цемент м500", "", "мешок")
        assert [point.price for point in found] == [D("380.00")] * (RETENTION_LIMIT + 1)


def test_nothing_is_archived_while_estimates_fit(tmp_path):
    _, Session = open_storage(tmp_path / "fits.db")
    with Session() as db:
        fill(db, UID, RETENTION_LIMIT)
        assert enforce_retention(db, UID) is None
        assert stored(db) == []


# --- Транзакция: половины операции не бывает ---


def test_a_failed_archive_leaves_the_estimate_alone(tmp_path, monkeypatch):
    _, Session = open_storage(tmp_path / "archive-fails.db")
    with Session() as db:
        fill(db, UID, RETENTION_LIMIT + 1)
        monkeypatch.setattr(history, "archive", _boom)

        with pytest.raises(RuntimeError, match="архив упал"):
            enforce_retention(db, UID)

        assert len(repo.list_estimates(db, UID, limit=99)) == RETENTION_LIMIT + 1
        assert stored(db) == []


def test_a_failed_delete_leaves_no_history_behind(tmp_path, monkeypatch):
    """Иначе в базе осталась бы цена от несостоявшегося удаления."""
    _, Session = open_storage(tmp_path / "delete-fails.db")
    with Session() as db:
        fill(db, UID, RETENTION_LIMIT + 1)
        monkeypatch.setattr(repo, "_drop_estimates", _boom)

        with pytest.raises(RuntimeError, match="архив упал"):
            enforce_retention(db, UID)

        assert stored(db) == []
        assert len(repo.list_estimates(db, UID, limit=99)) == RETENTION_LIMIT + 1


def _boom(*_args, **_kwargs):
    raise RuntimeError("архив упал")


# --- Чужого не видно ---


def test_two_users_never_see_each_other_prices(tmp_path):
    """Пересечение историй между людьми — это краудсорсинг, то есть 6b."""
    _, Session = open_storage(tmp_path / "two-users.db")
    with Session() as db:
        fill(db, UID, 1, cement(price="380"))
        fill(db, OTHER, 1, cement(price="999"))

        mine = history.lookup(db, UID, "цемент м500", "", "мешок")
        theirs = history.lookup(db, OTHER, "цемент м500", "", "мешок")

        assert [point.price for point in mine] == [D("380.00")]
        assert [point.price for point in theirs] == [D("999.00")]


def test_forget_wipes_only_that_user(tmp_path):
    """Команды удаления в боте пока нет — функция ждёт её (docs/known-issues.md)."""
    _, Session = open_storage(tmp_path / "forget.db")
    with Session() as db:
        fill(db, UID, RETENTION_LIMIT + 1)
        fill(db, OTHER, RETENTION_LIMIT + 1)
        enforce_retention(db, UID)
        enforce_retention(db, OTHER)

        assert history.forget(db, UID) == 1
        db.commit()
        assert stored(db, UID) == []
        assert len(stored(db, OTHER)) == 1


# --- Окно и дедупликация ---


def test_a_repeat_on_the_same_day_does_not_multiply_rows(tmp_path):
    _, Session = open_storage(tmp_path / "dedup.db")
    with Session() as db:
        fill(db, UID, RETENTION_LIMIT + 3)
        enforce_retention(db, UID)
        assert len(stored(db)) == 1

        # Повторный прогон архива на тех же данных ничего не добавляет.
        estimates = repo.list_estimates(db, UID, limit=99)
        assert history.archive(db, UID, [e.id for e in estimates]) == 0


def test_prices_older_than_the_window_are_not_suggested(tmp_path):
    """«За полгода» обязано быть правдой, иначе так говорить нельзя (ADR-018)."""
    _, Session = open_storage(tmp_path / "window.db")
    with Session() as db:
        fill(db, UID, 1)
        future = utcnow().date() + timedelta(days=history.WINDOW_DAYS + 1)
        assert history.lookup(db, UID, "цемент м500", "", "мешок", today=future) == []


def test_the_window_applies_to_live_positions_too(tmp_path):
    """Пять смет могут покрывать два года — ретеншен по времени не чистит."""
    _, Session = open_storage(tmp_path / "live-window.db")
    with Session() as db:
        fill(db, UID, 1)
        edge = utcnow().date() + timedelta(days=history.WINDOW_DAYS)
        assert history.lookup(db, UID, "цемент м500", "", "мешок", today=edge)

        beyond = edge + timedelta(days=1)
        assert history.lookup(db, UID, "цемент м500", "", "мешок", today=beyond) == []


def test_pruning_drops_what_left_the_window(tmp_path):
    _, Session = open_storage(tmp_path / "prune.db")
    with Session() as db:
        fill(db, UID, RETENTION_LIMIT + 1)
        enforce_retention(db, UID)

        future = utcnow().date() + timedelta(days=history.WINDOW_DAYS + 1)
        assert history.prune(db, UID, today=future) == 1
        db.commit()
        assert stored(db) == []


# --- Единицы: сравнивается сравнимое ---


def test_a_price_per_square_metre_is_never_offered_for_metres_run(tmp_path):
    _, Session = open_storage(tmp_path / "units.db")
    with Session() as db:
        fill(db, UID, 1, cement(name="Плинтус", unit="м²", unit_spoken=""))
        assert history.lookup(db, UID, "плинтус", "м.п.", "") == []
        assert history.lookup(db, UID, "плинтус", "м²", "")


def test_cases_of_one_spoken_unit_match(tmp_path):
    """В истории «мешков», спрашивают «мешок» — это одно и то же (ADR-017)."""
    _, Session = open_storage(tmp_path / "spoken.db")
    with Session() as db:
        fill(db, UID, 1, cement(unit_spoken="мешков"))
        assert history.lookup(db, UID, "цемент м500", "", "мешок")
