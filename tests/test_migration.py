"""Группа G: миграция старой базы в целые минорные единицы (docs/money.md §6.G)."""

from __future__ import annotations

import importlib
import pathlib
import sqlite3
import sys
from decimal import Decimal as D

import pytest

BOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "python3" / "webservice" / "telegram"

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


def load_bot(db_path: pathlib.Path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("ESTIMATE_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.syspath_prepend(str(BOT_DIR))
    sys.modules.pop("main_agent", None)
    return importlib.import_module("main_agent")


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


def test_g1_migration_adds_rates_and_integer_money(legacy_db, monkeypatch):
    bot = load_bot(legacy_db, monkeypatch)

    con = sqlite3.connect(legacy_db)
    columns = {row[1] for row in con.execute("PRAGMA table_info(positions)")}
    assert {"qty_milli", "price_kop"} <= columns

    rates = con.execute(
        "SELECT markup_work_bp, markup_material_bp FROM estimates WHERE id = 1"
    ).fetchone()
    assert rates == (600, 600)   # существующие сметы получают текущие 6%

    stored = con.execute(
        "SELECT name, qty_milli, price_kop FROM positions ORDER BY id"
    ).fetchall()
    con.close()
    assert stored == [
        ("Побелка", 1500, 10010),
        ("Стяжка", 2500, 10010),
        ("Гвозди", 100, 20),
    ]
    assert bot.DEFAULT_MARKUP_BP == 600


def test_g2_real_storage_imprecision_is_quantized_not_carried_over(legacy_db, monkeypatch):
    """0.1 в REAL — это 0.1000000000000000055…, в копейках это ровно 10."""
    con = sqlite3.connect(legacy_db)
    raw_qty = con.execute("SELECT qty FROM positions WHERE name = 'Гвозди'").fetchone()[0]
    con.close()
    assert D(str(raw_qty)) == D("0.1")

    load_bot(legacy_db, monkeypatch)

    con = sqlite3.connect(legacy_db)
    qty_milli, price_kop = con.execute(
        "SELECT qty_milli, price_kop FROM positions WHERE name = 'Гвозди'"
    ).fetchone()
    con.close()
    assert (qty_milli, price_kop) == (100, 20)
    assert isinstance(qty_milli, int) and isinstance(price_kop, int)


def test_migrated_estimate_totals_match_the_domain(legacy_db, monkeypatch):
    bot = load_bot(legacy_db, monkeypatch)
    with bot.SessionLocal() as db:
        estimate = db.get(bot.Estimate, 1)
        totals = bot.estimate_totals(db, 42, estimate)

    # 150.15 + 250.25 + 0.02 = 400.42 без наценки; строки с наценкой 159.16 + 265.27 + 0.02
    assert totals.subtotal == D("400.42")
    assert totals.total == D("424.45")
    assert totals.markup == totals.total - totals.subtotal
    assert sum(line.total for line in totals.lines) == totals.total


def test_fresh_database_needs_no_migration(tmp_path, monkeypatch):
    bot = load_bot(tmp_path / "new.db", monkeypatch)
    con = sqlite3.connect(tmp_path / "new.db")
    columns = {row[1] for row in con.execute("PRAGMA table_info(positions)")}
    con.close()
    assert {"qty_milli", "price_kop"} <= columns
    assert "qty" not in columns and "price" not in columns
    assert bot is not None
