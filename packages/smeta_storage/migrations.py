"""Создание схемы и мягкие миграции существующих баз."""

import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Connection, Engine, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import OperationalError

from .models import (
    DEFAULT_MARKUP_BP,
    Base,
    Estimate,
    PendingPosition,
    Position,
    PriceHistory,
    ShareLink,
    UserState,
    utcnow,
)

logger = logging.getLogger(__name__)

# Сказанная единица доезжает до документа заказчика, Sprint 5 (ADR-015).
POSITION_COLUMNS = {"unit_spoken": "VARCHAR(64)"}
PENDING_COLUMNS = {
    "unit_spoken": "VARCHAR(64)",
    "total_price": "VARCHAR(32)",
    "total_qty": "VARCHAR(32)",
    "total_unit": "VARCHAR(64)",
    "price_scope": "VARCHAR(16)",
    # Подсказка цены по своей истории, Sprint 6a (ADR-017).
    "hint_price": "VARCHAR(32)",
    "hint_median": "VARCHAR(32)",
    "hint_on": "DATE",
    "hint_times": "INTEGER",
}

# Черновик пошагового ввода, добавлен в Sprint 4 (ADR-010).
DRAFT_COLUMNS = {
    "draft_step": "VARCHAR(16)",
    "draft_name": "VARCHAR(255)",
    "draft_unit": "VARCHAR(32)",
    "draft_qty_milli": "INTEGER",
    "draft_price_kop": "INTEGER",
    "pending_line": "VARCHAR(512)",
}


def _add_missing_columns(conn: Connection, table: str, columns: dict[str, str]) -> None:
    existing = {c["name"] for c in sa_inspect(conn).get_columns(table)}
    for name, sql_type in columns.items():
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))


def migrate_money_to_integers(conn: Connection) -> list[str]:
    """Переводит qty/price из REAL в целые минорные единицы (ADR-004).

    Возвращает журнал строк, чьё хранимое значение не совпало с копейками после
    округления — это накопленная погрешность REAL-хранения.
    """
    conn.execute(text("ALTER TABLE positions ADD COLUMN qty_milli INTEGER DEFAULT 0"))
    conn.execute(text("ALTER TABLE positions ADD COLUMN price_kop INTEGER DEFAULT 0"))

    journal: list[str] = []
    for rid, qty_raw, price_raw in conn.execute(
        text("SELECT id, qty, price FROM positions")
    ).fetchall():
        qty = Decimal(str(qty_raw if qty_raw is not None else 0))
        price = Decimal(str(price_raw if price_raw is not None else 0))
        qty_milli = int(qty.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP).scaleb(3))
        price_kop = int(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP).scaleb(2))
        if Decimal(qty_milli).scaleb(-3) != qty or Decimal(price_kop).scaleb(-2) != price:
            journal.append(
                f"#{rid}: qty {qty} -> {qty_milli}/1000, price {price} -> {price_kop}/100"
            )
        conn.execute(
            text("UPDATE positions SET qty_milli = :q, price_kop = :p WHERE id = :i"),
            {"q": qty_milli, "p": price_kop, "i": rid},
        )

    for column in ("qty", "price"):
        try:
            conn.execute(text(f"ALTER TABLE positions DROP COLUMN {column}"))
        except OperationalError:
            logger.warning("Старая колонка positions.%s не удалена — SQLite слишком старый", column)
    return journal


# Категории уехали в english в Sprint 5. Пары старое -> новое.
CATEGORY_RENAMES = (("Работа", "work"), ("Материал", "material"))


def migrate_categories(conn: Connection, reverse: bool = False) -> int:
    """Переводит категории в english. Идемпотентна и обратима.

    Обе таблицы: в user_state лежит выбранная человеком категория, и оставить
    её русской значило бы уронить первый же хендлер на Category("Работа").

    WHERE берёт оба значения, поэтому повторный прогон ничего не портит, а
    reverse=True возвращает базу к русским значениям, если откатить придётся.
    """
    present = set(sa_inspect(conn).get_table_names())
    changed = 0
    for table in ("positions", "user_state"):
        if table not in present:
            continue
        for old, new in CATEGORY_RENAMES:
            source, target = (new, old) if reverse else (old, new)
            result = conn.execute(
                text(f"UPDATE {table} SET category = :target"
                     " WHERE category IN (:source, :target) AND category != :target"),
                {"source": source, "target": target},
            )
            changed += result.rowcount or 0
    return changed


# Всё, что смета нажила после первой схемы: ставки наценки (Sprint 2),
# версии и статусы (Sprint 7, money.md §1.3–1.4), отметка согласования.
ESTIMATE_COLUMNS = {
    "markup_work_bp": f"INTEGER NOT NULL DEFAULT {DEFAULT_MARKUP_BP}",
    "markup_material_bp": f"INTEGER NOT NULL DEFAULT {DEFAULT_MARKUP_BP}",
    "version": "INTEGER NOT NULL DEFAULT 1",
    "supersedes_id": "INTEGER REFERENCES estimates(id)",
    "status": "VARCHAR(16) NOT NULL DEFAULT 'draft'",
    "sent_at": "DATETIME",
    "frozen_subtotal_kop": "INTEGER",
    "frozen_markup_kop": "INTEGER",
    "frozen_total_kop": "INTEGER",
    "frozen_hash": "VARCHAR(64)",
    # Согласована смета, а не ссылка, по которой её открыли (ADR-020).
    "approved_at": "DATETIME",
}

# Что снимается откатом версий: ставки к версиям отношения не имеют.
VERSION_COLUMNS = tuple(ESTIMATE_COLUMNS)[2:]

VERSION_INDEX = "uq_estimate_version"


def migrate_estimate_versions(conn: Connection, reverse: bool = False) -> bool:
    """Догоняет таблицу смет до текущей схемы. Идемпотентна и обратима.

    Существующие сметы становятся черновиками первой версии: до Sprint 7
    других состояний не было, и объявить их отправленными задним числом
    значило бы заморозить то, чего никто не отправлял.

    Недостающие колонки добираются и тогда, когда версии уже есть: база могла
    остановиться на середине Sprint 7, и молчаливый пропуск обнаружился бы
    падением на первом же согласовании.
    """
    if "estimates" not in set(sa_inspect(conn).get_table_names()):
        return False
    existing = {c["name"] for c in sa_inspect(conn).get_columns("estimates")}

    if reverse:
        if "version" not in existing:
            return False
        conn.execute(text(f"DROP INDEX IF EXISTS {VERSION_INDEX}"))
        for name in VERSION_COLUMNS:
            if name in existing:
                try:
                    conn.execute(text(f"ALTER TABLE estimates DROP COLUMN {name}"))
                except OperationalError:  # pragma: no cover — очень старый SQLite
                    logger.warning("Колонка estimates.%s не удалена", name)
        return True

    _add_missing_columns(conn, "estimates", ESTIMATE_COLUMNS)
    if "version" in existing:
        return False
    conn.execute(text(
        "UPDATE estimates SET version = 1 WHERE version IS NULL"
    ))
    conn.execute(text(
        "UPDATE estimates SET status = 'draft' WHERE status IS NULL OR status = ''"
    ))
    # Уникальность (владелец, номер, версия) — не украшение: без неё две
    # ревизии могут получить один номер и заказчик не различит документы.
    conn.execute(text(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {VERSION_INDEX}"
        " ON estimates (user_id, number, version)"
    ))
    return True


def _ensure_table(conn: Connection, table, reverse: bool) -> bool:
    """Заводит одну таблицу целиком. Идемпотентна в обе стороны.

    Возвращает True, если что-то сделала. Обратный ход сносит таблицу — для
    новой таблицы это и есть полный откат.
    """
    present = table.name in set(sa_inspect(conn).get_table_names())
    if reverse:
        if present:
            conn.execute(text(f"DROP TABLE {table.name}"))
        return present
    if present:
        return False
    Base.metadata.create_all(bind=conn, tables=[table])
    return True


def migrate_price_history(conn: Connection, reverse: bool = False) -> bool:
    """Заводит таблицу истории своих цен, Sprint 6a (ADR-017).

    Откат сносит её целиком, и это осознанно: история восстановима из смет
    ровно настолько, насколько сметы ещё живы, а полумеры при откате хуже
    честной потери.
    """
    return _ensure_table(conn, PriceHistory.__table__, reverse)


def migrate_share_links(conn: Connection, reverse: bool = False) -> bool:
    """Заводит таблицу публичных ссылок, Sprint 7 (ADR-020).

    Откат сносит её целиком — и это именно то поведение, которое нужно:
    выданные ссылки перестают работать все сразу. Ничего, кроме доступа, в
    таблице не хранится, восстанавливать нечего.
    """
    return _ensure_table(conn, ShareLink.__table__, reverse)


def _migrate_orphan_positions(conn: Connection) -> None:
    """Позициям без estimate_id создаём смету, иначе они не видны ни в одной."""
    users = conn.execute(
        text("SELECT DISTINCT user_id FROM positions WHERE estimate_id IS NULL")
    ).fetchall()
    for (uid,) in users:
        row = conn.execute(
            text("SELECT MAX(number) FROM estimates WHERE user_id = :uid"), {"uid": uid}
        ).fetchone()
        next_num = (row[0] or 0) + 1
        now = utcnow().isoformat(sep=" ")
        conn.execute(
            text(
                "INSERT INTO estimates (user_id, number, name, markup_work_bp,"
                " markup_material_bp, created_at, updated_at)"
                " VALUES (:uid, :num, :name, :bp, :bp, :c, :c)"
            ),
            {"uid": uid, "num": next_num, "name": f"Смета №{next_num}",
             "bp": DEFAULT_MARKUP_BP, "c": now},
        )
        est_id = conn.execute(
            text("SELECT id FROM estimates WHERE user_id = :uid AND number = :num"),
            {"uid": uid, "num": next_num},
        ).fetchone()[0]
        conn.execute(
            text("UPDATE positions SET estimate_id = :eid WHERE user_id = :uid"
                 " AND estimate_id IS NULL"),
            {"eid": est_id, "uid": uid},
        )


def bootstrap(engine: Engine) -> None:
    """Создаёт схему и догоняет старые базы до текущей."""
    with engine.begin() as conn:
        tables = sa_inspect(conn).get_table_names()

        if "positions" not in tables and "estimates" not in tables:
            Base.metadata.create_all(bind=conn)
            return

        migrate_price_history(conn)
        migrate_estimate_versions(conn)
        migrate_share_links(conn)

        # Ставки догоняются вместе с версиями: одна таблица — одно место.
        _ensure_table(conn, Estimate.__table__, reverse=False)

        if not _ensure_table(conn, UserState.__table__, reverse=False):
            _add_missing_columns(conn, "user_state", DRAFT_COLUMNS)

        # Предпросмотр распознанной пачки, добавлен в Sprint 5 (ADR-012).
        if not _ensure_table(conn, PendingPosition.__table__, reverse=False):
            _add_missing_columns(conn, "pending_positions", PENDING_COLUMNS)

        if "positions" not in tables:
            Base.metadata.create_all(bind=conn, tables=[Position.__table__])
            migrate_categories(conn)
            return

        columns = {c["name"] for c in sa_inspect(conn).get_columns("positions")}
        if "estimate_id" not in columns:
            conn.execute(text("ALTER TABLE positions ADD COLUMN estimate_id INTEGER"))
        if "unit" not in columns:
            conn.execute(text("ALTER TABLE positions ADD COLUMN unit VARCHAR(32) DEFAULT ''"))
        _add_missing_columns(conn, "positions", POSITION_COLUMNS)
        if "price_kop" not in columns:
            journal = migrate_money_to_integers(conn)
            logger.info("Миграция денег в целые: строк с расхождением — %d", len(journal))
            for entry in journal:
                logger.info("  %s", entry)

        renamed = migrate_categories(conn)
        if renamed:
            logger.info("Категории переведены в english: строк — %d", renamed)

        _migrate_orphan_positions(conn)
