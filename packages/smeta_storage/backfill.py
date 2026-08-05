"""Миграции данных: перенос значений в уже существующих строках.

Отделено от migrations.py по границе «схема / данные». Причина не в длине
файла: у этих двух видов миграций разная цена ошибки. Недобранная колонка
роняет первый же запрос — заметно сразу. Неверно перенесённое значение
остаётся в базе молча и обнаруживается, когда по нему уже выписан документ.

Всё здесь обязано быть идемпотентным: миграция запускается при каждом старте.
"""

import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Connection, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import OperationalError

from .models import DEFAULT_MARKUP_BP, Base, PriceHistory, utcnow

logger = logging.getLogger(__name__)

# Категории уехали в english в Sprint 5. Пары старое -> новое.
CATEGORY_RENAMES = (("Работа", "work"), ("Материал", "material"))


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


def migrate_snapshot_format(conn: Connection) -> int:
    """Проставляет формат слепка тем сметам, что заморожены до его появления.

    Формат 1 — единственный, который существовал до этой колонки, поэтому
    «заморожена и формат неизвестен» и «заморожена форматом 1» — это одно и то
    же утверждение об истории. Записывается оно ровно здесь и один раз: дальше
    формат ставит send(), а недостающее значение у отправленной сметы — повод
    отказать в документе, а не догадываться (ADR-023 про молчаливые дефолты).
    """
    result = conn.execute(text(
        "UPDATE estimates SET frozen_format = 1"
        " WHERE frozen_hash IS NOT NULL AND frozen_format IS NULL"
    ))
    return result.rowcount or 0


def migrate_orphan_positions(conn: Connection) -> None:
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


# Состав ключа дня после Sprint 9. Проверяется по факту, а не по номеру
# версии: база могла остановиться на середине.
PRICE_HISTORY_KEY = (
    "user_id", "name_norm", "unit", "unit_spoken", "category", "performer",
    "observed_on",
)


def migrate_price_history_key(conn: Connection) -> bool:
    """Перестраивает таблицу под ключ дня с категорией и исполнителем (ADR-028).

    SQLite не умеет менять UNIQUE в существующей таблице — только пересобрать.
    Порядок выбран так, чтобы данные не оставались без крыши: копия делается
    до сноса, вставка — после создания новой таблицы, и всё это внутри одной
    транзакции вызывающего.

    Новый ключ шире старого, поэтому строки, уникальные по старому, уникальны
    и по новому: вставка не может упереться в конфликт.
    """
    if "price_history" not in set(sa_inspect(conn).get_table_names()):
        return False
    keys = {
        tuple(constraint["column_names"])
        for constraint in sa_inspect(conn).get_unique_constraints("price_history")
    }
    if PRICE_HISTORY_KEY in keys:
        return False

    columns = ", ".join(column.name for column in PriceHistory.__table__.columns)
    conn.execute(text("CREATE TABLE price_history_old AS SELECT * FROM price_history"))
    conn.execute(text("DROP TABLE price_history"))
    Base.metadata.create_all(bind=conn, tables=[PriceHistory.__table__])
    conn.execute(text(
        f"INSERT INTO price_history ({columns}) SELECT {columns} FROM price_history_old"
    ))
    conn.execute(text("DROP TABLE price_history_old"))
    return True
