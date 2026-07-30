"""Группа G: миграция старой базы в целые минорные единицы (docs/money.md §6.G)."""

import sqlite3
from decimal import Decimal as D

import pytest

from conftest import open_storage
from smeta_storage import DEFAULT_MARKUP_BP, Estimate, positions

OLD_SCHEMA = """
CREATE TABLE estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, number INTEGER,
    name VARCHAR(255), created_at DATETIME, updated_at DATETIME
);
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, estimate_id INTEGER,
    category VARCHAR(16), name VARCHAR(255), unit VARCHAR(32),
    qty NUMERIC(18,3), price NUMERIC(18,2), created_at DATETIME
);
"""


@pytest.fixture
def legacy_db(tmp_path):
    """База в старой схеме: деньги в NUMERIC, то есть физически в REAL."""
    path = tmp_path / "estimate.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.execute(
        "INSERT INTO estimates (id, user_id, number, name) VALUES (1, 42, 1, 'Смета №1')"
    )
    con.executemany(
        "INSERT INTO positions (user_id, estimate_id, category, name, unit, qty, price)"
        " VALUES (42, 1, ?, ?, '', ?, ?)",
        [
            ("Работа", "Побелка", 1.5, 100.10),
            ("Работа", "Стяжка", 2.5, 100.10),
            ("Материал", "Гвозди", 0.1, 0.2),   # значение, которое REAL хранит неточно
        ],
    )
    con.commit()
    con.close()
    return path


def test_g1_migration_adds_rates_and_integer_money(legacy_db):
    open_storage(legacy_db)

    con = sqlite3.connect(legacy_db)
    columns = {row[1] for row in con.execute("PRAGMA table_info(positions)")}
    assert {"qty_milli", "price_kop"} <= columns

    rates = con.execute(
        "SELECT markup_work_bp, markup_material_bp FROM estimates WHERE id = 1"
    ).fetchone()
    assert rates == (DEFAULT_MARKUP_BP, DEFAULT_MARKUP_BP)   # существующие сметы получают 6%

    stored = con.execute(
        "SELECT name, qty_milli, price_kop FROM positions ORDER BY id"
    ).fetchall()
    con.close()
    assert stored == [
        ("Побелка", 1500, 10010),
        ("Стяжка", 2500, 10010),
        ("Гвозди", 100, 20),
    ]


def test_g1_migration_creates_the_user_state_table(legacy_db):
    open_storage(legacy_db)
    con = sqlite3.connect(legacy_db)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "user_state" in tables


def test_g2_real_storage_imprecision_is_quantized_not_carried_over(legacy_db):
    """0.1 в REAL — это 0.1000000000000000055…, в копейках это ровно 10."""
    con = sqlite3.connect(legacy_db)
    raw_qty = con.execute("SELECT qty FROM positions WHERE name = 'Гвозди'").fetchone()[0]
    con.close()
    assert D(str(raw_qty)) == D("0.1")

    open_storage(legacy_db)

    con = sqlite3.connect(legacy_db)
    qty_milli, price_kop = con.execute(
        "SELECT qty_milli, price_kop FROM positions WHERE name = 'Гвозди'"
    ).fetchone()
    con.close()
    assert (qty_milli, price_kop) == (100, 20)
    assert isinstance(qty_milli, int)
    assert isinstance(price_kop, int)


def test_migrated_estimate_totals_match_the_domain(legacy_db):
    _, Session = open_storage(legacy_db)
    with Session() as db:
        estimate = db.get(Estimate, 1)
        totals = positions.totals(db, 42, estimate)

    # 150.15 + 250.25 + 0.02 = 400.42 без наценки; с наценкой 159.16 + 265.27 + 0.02
    assert totals.subtotal == D("400.42")
    assert totals.total == D("424.45")
    assert totals.markup == totals.total - totals.subtotal
    assert sum(line.total for line in totals.lines) == totals.total


def test_fresh_database_needs_no_migration(tmp_path):
    path = tmp_path / "new.db"
    open_storage(path)
    con = sqlite3.connect(path)
    columns = {row[1] for row in con.execute("PRAGMA table_info(positions)")}
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"qty_milli", "price_kop", "unit"} <= columns
    assert "qty" not in columns
    assert "price" not in columns
    assert {"estimates", "positions", "user_state"} <= tables


def test_positions_without_an_estimate_get_one(tmp_path):
    """Позиции из самой первой версии схемы жили без estimate_id."""
    path = tmp_path / "orphans.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.executemany(
        "INSERT INTO positions (user_id, estimate_id, category, name, unit, qty, price)"
        " VALUES (?, NULL, ?, ?, '', ?, ?)",
        [
            (7, "Работа", "Побелка", 10.0, 100.0),
            (7, "Материал", "Гвозди", 5.0, 20.0),
            (8, "Работа", "Стяжка", 3.0, 500.0),
        ],
    )
    con.commit()
    con.close()

    _, Session = open_storage(path)
    con = sqlite3.connect(path)
    orphans = con.execute("SELECT COUNT(*) FROM positions WHERE estimate_id IS NULL").fetchone()[0]
    estimates = con.execute("SELECT user_id, number, markup_work_bp FROM estimates").fetchall()
    con.close()

    assert orphans == 0
    assert sorted(estimates) == [(7, 1, DEFAULT_MARKUP_BP), (8, 1, DEFAULT_MARKUP_BP)]

    with Session() as db:
        estimate = db.get(Estimate, 1)
        assert len(positions.load(db, estimate.user_id, estimate.id)) == 2


def test_migration_is_idempotent(legacy_db):
    """Повторный подъём той же базы не должен ничего ломать."""
    open_storage(legacy_db)
    _, Session = open_storage(legacy_db)
    with Session() as db:
        totals = positions.totals(db, 42, db.get(Estimate, 1))
    assert totals.total == D("424.45")
