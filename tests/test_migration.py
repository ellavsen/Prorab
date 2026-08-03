"""Группа G: миграция старой базы в целые минорные единицы (docs/money.md §6.G)."""

import sqlite3
from decimal import Decimal as D

import pytest

from conftest import open_storage
from smeta_storage import (
    DEFAULT_MARKUP_BP,
    Estimate,
    migrate_share_links,
    positions,
    verified_totals,
)

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


# База времён Sprint 7: версии и заморозка уже есть, основания ставки и версии
# формата слепка ещё нет. Ровно то состояние, в котором находится любая живая
# установка на момент этой миграции.
SPRINT7_SCHEMA = """
CREATE TABLE estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, number INTEGER,
    version INTEGER DEFAULT 1, supersedes_id INTEGER, name VARCHAR(255),
    status VARCHAR(16) DEFAULT 'draft',
    markup_work_bp INTEGER DEFAULT 600, markup_material_bp INTEGER DEFAULT 600,
    created_at DATETIME, updated_at DATETIME, sent_at DATETIME,
    frozen_subtotal_kop INTEGER, frozen_markup_kop INTEGER,
    frozen_total_kop INTEGER, frozen_hash VARCHAR(64), approved_at DATETIME
);
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, estimate_id INTEGER,
    category VARCHAR(16), name VARCHAR(255), unit VARCHAR(32),
    unit_spoken VARCHAR(64), qty_milli INTEGER, price_kop INTEGER,
    created_at DATETIME
);
"""

# Слепок, посчитанный форматом 1 по этим двум позициям и ставкам 6/6. Литерал,
# а не вызов: он изображает то, что уже лежит в чужой базе, и следовать за
# правкой кода не должен. Порядок позиций в слепок входит и берётся такой же,
# как отдаёт positions.load — ORDER BY category, id, то есть материалы раньше
# работ.
SPRINT7_HASH = "7979a7e586d71538d7be0e3bfd41c8344d7918a6f219148579411a51ffa50e37"


@pytest.fixture
def sprint7_db(tmp_path):
    path = tmp_path / "sprint7.db"
    con = sqlite3.connect(path)
    con.executescript(SPRINT7_SCHEMA)
    con.execute(
        "INSERT INTO estimates (id, user_id, number, name, status, sent_at,"
        " frozen_subtotal_kop, frozen_markup_kop, frozen_total_kop, frozen_hash)"
        " VALUES (1, 42, 1, 'Смета №1', 'sent', '2026-01-15 10:00:00',"
        " 52015, 3121, 55136, ?)",
        (SPRINT7_HASH,),
    )
    con.executemany(
        "INSERT INTO positions (user_id, estimate_id, category, name, unit,"
        " unit_spoken, qty_milli, price_kop) VALUES (42, 1, ?, ?, '', '', ?, ?)",
        [("work", "Побелка", 1500, 10010), ("material", "Гвозди", 1000000, 37)],
    )
    con.commit()
    con.close()
    return path


def test_a_document_sent_before_the_migration_is_still_issued_after_it(sprint7_db):
    """Главная проверка шага: правка формулы не отняла у людей их документы.

    Смета отправлена кодом Sprint 7 и подтверждена слепком формата 1. После
    миграции текущим форматом стал второй — и если бы проверка шла текущим, а
    не записанным, эта смета перестала бы выдаваться, а заказчик увидел бы
    нейтральный 404 без объяснения причины.
    """
    _engine, Session = open_storage(sprint7_db)
    with Session() as db:
        estimate = db.get(Estimate, 1)
        assert (estimate.rate_base, estimate.frozen_format) == ("cost", 1)
        assert verified_totals(db, estimate).total == D("551.36") == estimate.frozen_total


def test_the_migration_stamps_the_format_only_on_what_was_frozen(sprint7_db):
    """Черновику формат не нужен: его нечем и незачем подтверждать."""
    con = sqlite3.connect(sprint7_db)
    con.execute(
        "INSERT INTO estimates (id, user_id, number, name, status)"
        " VALUES (2, 42, 2, 'Черновик', 'draft')"
    )
    con.commit()
    con.close()

    open_storage(sprint7_db)

    con = sqlite3.connect(sprint7_db)
    stamped = dict(con.execute("SELECT id, frozen_format FROM estimates").fetchall())
    con.close()
    assert stamped == {1: 1, 2: None}


def test_a_frozen_estimate_without_a_format_refuses_instead_of_guessing(sprint7_db):
    """Если строку миграция не застала — документ не выдаётся.

    Догадаться «наверное, формат 1» было бы тем же молчаливым дефолтом, ради
    отказа от которого формат и версионируется.
    """
    _engine, Session = open_storage(sprint7_db)
    with Session() as db:
        estimate = db.get(Estimate, 1)
        estimate.frozen_format = None
        with pytest.raises(ValueError, match="формат"):
            verified_totals(db, estimate)


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


def test_migration_creates_the_preview_table(legacy_db):
    """Старая база догоняется до Sprint 5, а не падает на первом предпросмотре."""
    open_storage(legacy_db)
    con = sqlite3.connect(legacy_db)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "pending_positions" in tables


def test_migration_creates_the_share_link_table(legacy_db):
    """Старая база догоняется до Sprint 7, а не падает на первом /send."""
    open_storage(legacy_db)
    con = sqlite3.connect(legacy_db)
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert "share_links" in tables


def test_the_share_link_migration_is_idempotent_and_reversible(legacy_db):
    """Откат сносит таблицу целиком: все выданные ссылки перестают работать сразу."""
    engine, _Session = open_storage(legacy_db)
    with engine.begin() as conn:
        assert migrate_share_links(conn) is False, "таблица уже есть — делать нечего"
        assert migrate_share_links(conn, reverse=True) is True
        assert migrate_share_links(conn, reverse=True) is False
        assert migrate_share_links(conn) is True


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
        totals = verified_totals(db, estimate)

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
        totals = verified_totals(db, db.get(Estimate, 1))
    assert totals.total == D("424.45")


# --- Категории уехали в english, Sprint 5 ---

def test_categories_become_english(legacy_db):
    open_storage(legacy_db)
    con = sqlite3.connect(legacy_db)
    stored = {row[0] for row in con.execute("SELECT DISTINCT category FROM positions")}
    con.close()
    assert stored == {"work", "material"}


def test_the_category_migration_is_idempotent(legacy_db):
    """Второй прогон не должен ничего трогать: WHERE берёт оба значения."""
    from smeta_storage import build_engine, migrate_categories

    open_storage(legacy_db)
    engine = build_engine(f"sqlite:///{legacy_db}")
    with engine.begin() as conn:
        assert migrate_categories(conn) == 0
    engine.dispose()


def test_the_category_migration_can_be_rolled_back(legacy_db):
    """Обратная миграция существует на случай отката коммита."""
    from smeta_storage import build_engine, migrate_categories

    open_storage(legacy_db)
    engine = build_engine(f"sqlite:///{legacy_db}")
    with engine.begin() as conn:
        assert migrate_categories(conn, reverse=True) > 0
    engine.dispose()

    con = sqlite3.connect(legacy_db)
    stored = {row[0] for row in con.execute("SELECT DISTINCT category FROM positions")}
    con.close()
    assert stored == {"Работа", "Материал"}


def test_spoken_unit_column_is_added(legacy_db):
    open_storage(legacy_db)
    con = sqlite3.connect(legacy_db)
    columns = {row[1] for row in con.execute("PRAGMA table_info(positions)")}
    con.close()
    assert "unit_spoken" in columns
