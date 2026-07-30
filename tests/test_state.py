"""Состояние диалога живёт в базе (ADR-005). Главный тест DoD Sprint 2."""

from decimal import Decimal as D

from conftest import open_storage
from smeta_core import Category, parse_position_line
from smeta_storage import (
    RETENTION_LIMIT,
    create_estimate,
    current_estimate,
    enforce_retention,
    get_category,
    positions,
    set_category,
    set_current_estimate,
    touch_estimate,
    user_state,
)

UID = 42


def test_active_estimate_survives_a_restart(tmp_path):
    """Ровно тот случай, который раньше ломался молча.

    «Вторая» свежее по updated_at, поэтому прежний фолбэк «взять самую свежую»
    вернул бы её — и следующая позиция уехала бы не в ту смету.
    """
    path = tmp_path / "restart.db"
    engine, Session = open_storage(path)
    with Session() as db:
        first = create_estimate(db, UID, name="Первая")
        create_estimate(db, UID, name="Вторая")
        set_current_estimate(db, UID, first.id)
        set_category(db, UID, "Работа")
        first_id = first.id
    engine.dispose()

    # Рестарт процесса: новый engine, новая фабрика сессий, тот же файл.
    _, Session = open_storage(path)
    with Session() as db:
        restored = current_estimate(db, UID)
        assert restored.id == first_id
        assert restored.name == "Первая"
        assert get_category(db, UID) == "Работа"


def test_positions_land_in_the_chosen_estimate_after_a_restart(tmp_path):
    path = tmp_path / "restart2.db"
    engine, Session = open_storage(path)
    with Session() as db:
        first = create_estimate(db, UID, name="Первая")
        create_estimate(db, UID, name="Вторая")
        set_current_estimate(db, UID, first.id)
        first_id = first.id
    engine.dispose()

    _, Session = open_storage(path)
    with Session() as db:
        estimate = current_estimate(db, UID)
        positions.add(db, UID, estimate.id, parse_position_line("Побелка, 10, 100", Category.WORK))
        db.commit()
        assert len(positions.load(db, UID, first_id)) == 1


def test_first_contact_creates_an_estimate(tmp_path):
    _, Session = open_storage(tmp_path / "first.db")
    with Session() as db:
        estimate = current_estimate(db, UID)
        assert estimate.number == 1
        assert user_state(db, UID).current_estimate_id == estimate.id


def test_first_contact_adopts_an_existing_estimate(tmp_path):
    """Старые базы состояния не имеют — тогда берётся самая свежая смета."""
    _, Session = open_storage(tmp_path / "adopt.db")
    with Session() as db:
        create_estimate(db, UID, name="Старая")
        newest = create_estimate(db, UID, name="Новая")
        assert current_estimate(db, UID).id == newest.id


def test_category_starts_empty_and_can_be_reset(tmp_path):
    _, Session = open_storage(tmp_path / "cat.db")
    with Session() as db:
        assert get_category(db, UID) is None
        set_category(db, UID, "Материал")
        assert get_category(db, UID) == "Материал"
        set_category(db, UID, None)
        assert get_category(db, UID) is None


def test_state_is_per_user(tmp_path):
    _, Session = open_storage(tmp_path / "users.db")
    with Session() as db:
        mine = create_estimate(db, 1, name="Моя")
        theirs = create_estimate(db, 2, name="Их")
        set_current_estimate(db, 1, mine.id)
        set_current_estimate(db, 2, theirs.id)
        set_category(db, 1, "Работа")

        assert current_estimate(db, 1).id == mine.id
        assert current_estimate(db, 2).id == theirs.id
        assert get_category(db, 2) is None


def test_retention_reports_the_switch_instead_of_doing_it_silently(tmp_path):
    _, Session = open_storage(tmp_path / "retention.db")
    with Session() as db:
        oldest = create_estimate(db, UID, name="Самая старая")
        set_current_estimate(db, UID, oldest.id)
        for index in range(RETENTION_LIMIT):
            estimate = create_estimate(db, UID, name=f"Смета {index}")
            touch_estimate(db, estimate)

        switched = enforce_retention(db, UID)
        assert switched is not None, "переключение обязано быть возвращено вызывающему"
        assert switched.id != oldest.id
        assert current_estimate(db, UID).id == switched.id


def test_retention_keeps_quiet_when_nothing_was_dropped(tmp_path):
    _, Session = open_storage(tmp_path / "retention2.db")
    with Session() as db:
        estimate = create_estimate(db, UID, name="Одна")
        set_current_estimate(db, UID, estimate.id)
        assert enforce_retention(db, UID) is None
        assert current_estimate(db, UID).id == estimate.id


def test_deleted_current_estimate_falls_back_without_crashing(tmp_path):
    """SQLite по умолчанию не применяет ON DELETE, поэтому фолбэк нужен в коде."""
    _, Session = open_storage(tmp_path / "gone.db")
    with Session() as db:
        gone = create_estimate(db, UID, name="Удалённая")
        kept = create_estimate(db, UID, name="Оставшаяся")
        set_current_estimate(db, UID, gone.id)
        db.delete(gone)
        db.commit()

        assert current_estimate(db, UID).id == kept.id
        assert user_state(db, UID).current_estimate_id == kept.id


def test_totals_use_the_estimate_own_rate(tmp_path):
    _, Session = open_storage(tmp_path / "rates.db")
    with Session() as db:
        cheap = create_estimate(db, UID, name="Без наценки", markup_work_bp=0)
        rich = create_estimate(db, UID, name="С наценкой", markup_work_bp=1000)
        line = parse_position_line("Побелка, 1, 1000", Category.WORK)
        positions.add(db, UID, cheap.id, line)
        positions.add(db, UID, rich.id, line)
        db.commit()

        assert positions.totals(db, UID, cheap).total == D("1000.00")
        assert positions.totals(db, UID, rich).total == D("1100.00")


def test_renewing_an_estimate_copies_name_and_rates(tmp_path):
    from smeta_storage import create_new_estimate_like

    _, Session = open_storage(tmp_path / "renew.db")
    with Session() as db:
        source = create_estimate(
            db, UID, name="Объект на Ленина", markup_work_bp=1500, markup_material_bp=300
        )
        positions.add(db, UID, source.id, parse_position_line("Побелка, 10, 100", Category.WORK))
        db.commit()

        created = create_new_estimate_like(db, UID, source)
        assert created.name == source.name
        assert created.number == source.number + 1
        assert (created.markup_work_bp, created.markup_material_bp) == (1500, 300)
        assert positions.load(db, UID, created.id) == []      # новая смета пустая
        assert len(positions.load(db, UID, source.id)) == 1    # старая не тронута
        assert current_estimate(db, UID).id == created.id


def test_clearing_positions_keeps_the_estimate(tmp_path):
    _, Session = open_storage(tmp_path / "clear.db")
    with Session() as db:
        estimate = create_estimate(db, UID, name="Смета")
        positions.add(db, UID, estimate.id, parse_position_line("Побелка, 10, 100", Category.WORK))
        db.commit()

        positions.clear(db, UID, estimate.id)
        db.commit()
        assert positions.load(db, UID, estimate.id) == []
        assert db.get(type(estimate), estimate.id) is not None


def test_getting_a_position_is_scoped_to_the_owner_and_estimate(tmp_path):
    _, Session = open_storage(tmp_path / "scope.db")
    with Session() as db:
        mine = create_estimate(db, 1, name="Моя")
        other = create_estimate(db, 2, name="Чужая")
        row = positions.add(db, 1, mine.id, parse_position_line("Побелка, 10, 100", Category.WORK))
        db.commit()

        assert positions.get(db, 1, mine.id, row.id) is not None
        assert positions.get(db, 2, other.id, row.id) is None   # чужую не отдаём
        assert positions.get(db, 1, other.id, row.id) is None   # и не из той сметы


def test_merge_backfills_a_missing_unit(tmp_path):
    """Строка из старой базы без единицы получает её при следующем вводе."""
    from smeta_storage import Position

    _, Session = open_storage(tmp_path / "backfill.db")
    with Session() as db:
        estimate = create_estimate(db, UID, name="Смета")
        db.add(Position(
            user_id=UID, estimate_id=estimate.id, category="Работа",
            name="Побелка", unit="", qty_milli=10_000, price_kop=10_000,
        ))
        db.commit()

        positions.add(db, UID, estimate.id, parse_position_line("Побелка, 5 м2, 100", Category.WORK))
        db.commit()
        rows = positions.load(db, UID, estimate.id)

    assert len(rows) == 1
    assert rows[0].qty == D("15")
    assert rows[0].unit == "м²"
