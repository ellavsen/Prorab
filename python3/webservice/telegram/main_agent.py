import asyncio
import html
import logging
import os
import re
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple, Dict, List

from dotenv import load_dotenv
load_dotenv()

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
)

from sqlalchemy import (
    create_engine,
    Integer,
    String,
    Numeric,
    DateTime,
    select,
    delete,
    func,
    text,
    ForeignKey,
    inspect as sa_inspect,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side

# =========================
# Config & Logging
# =========================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("estimate-bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN в окружении. Проверь .env")

DB_URL = os.getenv("ESTIMATE_DB_URL", "sqlite:///estimate.db")
TAX_RATE = Decimal("0.06")  # +6%
RETENTION_LIMIT = 5          # хранить последние N смет на пользователя

# =========================
# Database setup
# =========================

class Base(DeclarativeBase):
    pass

class Estimate(Base):
    __tablename__ = "estimates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    number: Mapped[int] = mapped_column(Integer)  # нумерация внутри пользователя
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    estimate_id: Mapped[Optional[int]] = mapped_column(ForeignKey("estimates.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(16))  # "Материал" | "Работа"
    name: Mapped[str] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(32), default="")  # оставлено для совместимости
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 3), default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def sum_line_no_tax(self) -> Decimal:
        return (self.qty or Decimal("0")) * (self.price or Decimal("0"))

    def sum_line_with_tax(self) -> Decimal:
        return self.sum_line_no_tax() * (Decimal("1") + TAX_RATE)

engine = create_engine(DB_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

def bootstrap_schema_and_migrate():
    """Создаём таблицы и мягко мигрируем старые данные (если нет estimates/estimate_id)."""
    with engine.begin() as conn:
        inspector = sa_inspect(conn)
        tables = inspector.get_table_names()

        # если база пустая — создаём всё сразу
        if "positions" not in tables and "estimates" not in tables:
            Base.metadata.create_all(bind=conn)
            return

        if "estimates" not in tables:
            Base.metadata.create_all(bind=conn, tables=[Estimate.__table__])

        cols = {c["name"] for c in inspector.get_columns("positions")} if "positions" in tables else set()
        if "positions" not in tables:
            Base.metadata.create_all(bind=conn, tables=[Position.__table__])
            return

        if "estimate_id" not in cols:
            conn.execute(text("ALTER TABLE positions ADD COLUMN estimate_id INTEGER"))

        # Создадим дефолтную смету для пользователей, у кого есть позиции без estimate_id
        users = conn.execute(text("SELECT DISTINCT user_id FROM positions WHERE estimate_id IS NULL")).fetchall()
        for (uid,) in users:
            row = conn.execute(text("SELECT MAX(number) FROM estimates WHERE user_id = :uid"), {"uid": uid}).fetchone()
            next_num = (row[0] or 0) + 1
            name = f"Смета №{next_num}"
            now = datetime.utcnow().isoformat(sep=" ")
            conn.execute(
                text("INSERT INTO estimates (user_id, number, name, created_at, updated_at) VALUES (:uid, :num, :name, :c, :u)"),
                {"uid": uid, "num": next_num, "name": name, "c": now, "u": now},
            )
            est_id = conn.execute(
                text("SELECT id FROM estimates WHERE user_id = :uid AND number = :num"),
                {"uid": uid, "num": next_num}
            ).fetchone()[0]
            conn.execute(
                text("UPDATE positions SET estimate_id = :eid WHERE user_id = :uid AND estimate_id IS NULL"),
                {"eid": est_id, "uid": uid}
            )

bootstrap_schema_and_migrate()

# =========================
# Runtime per-user state
# =========================

user_category: Dict[int, Optional[str]] = {}      # "Материал"|"Работа"|None
current_estimate_cache: Dict[int, int] = {}       # user_id -> estimate_id (для быстрого доступа)

# =========================
# Helpers: parsing & formatting
# =========================

RE_VOLUME = re.compile(
    r"(?P<num>[0-9]+([.,][0-9]+)?)\s*(?P<unit>(м2|м3|м^2|м^3|м²|м³|пм|шт\.?|кг|т|м|см|мм)?)$",
    flags=re.IGNORECASE,
)

def to_decimal(v: str) -> Decimal:
    v = v.strip().replace(" ", "").replace(",", ".")
    if v == "":
        raise InvalidOperation("empty")
    return Decimal(v)

def short_money(d: Decimal) -> str:
    return f"{d:.2f}".replace(".", ",")

def esc(s) -> str:
    """Экранирует пользовательский текст для сообщений с parse_mode=HTML."""
    return html.escape(str(s))

def reply_kb_start():
    return ReplyKeyboardMarkup([[KeyboardButton("Начнём")]], resize_keyboard=True, one_time_keyboard=True)

def reply_kb_categories():
    return ReplyKeyboardMarkup([[KeyboardButton("Работа"), KeyboardButton("Материал")]], resize_keyboard=True)

# --- INPUT FORMAT (актуальный) ---
# Материал:  Наименование, количество, цена
def parse_material_line(text_line: str) -> Tuple[str, Decimal, Decimal]:
    parts = [p.strip() for p in text_line.split(",")]
    if len(parts) < 3:
        raise ValueError("Материал: ожидается 3 значения: Наименование, количество, цена")
    name = parts[0]
    qty = to_decimal(parts[1])   # <-- теперь второе поле = КОЛИЧЕСТВО
    price = to_decimal(parts[2]) # <-- третье поле = ЦЕНА
    return name, price, qty      # возвращаем в порядке (name, price, qty), как ждёт add_line


# Работа:    Вид работы, количество, цена за единицу
def parse_work_line(text_line: str) -> Tuple[str, Decimal, Decimal]:
    parts = [p.strip() for p in text_line.split(",")]
    if len(parts) < 3:
        raise ValueError("Работа: ожидается 3 значения: Вид работы, количество, цена за единицу")
    name = parts[0]
    vol = parts[1].replace(" ", "")
    m = RE_VOLUME.search(vol)
    qty = to_decimal(m.group("num")) if m else to_decimal(vol)
    price = to_decimal(parts[2])
    return name, price, qty

# =========================
# Estimate helpers
# =========================

def get_current_estimate(db: Session, uid: int) -> Estimate:
    """Берём из кэша или самую свежую смету; если нет — создаём №1."""
    if uid in current_estimate_cache:
        est = db.get(Estimate, current_estimate_cache[uid])
        if est:
            return est

    est = db.execute(
        select(Estimate).where(Estimate.user_id == uid).order_by(Estimate.updated_at.desc())
    ).scalars().first()
    if est:
        current_estimate_cache[uid] = est.id
        return est

    num = 1
    name = f"Смета №{num}"
    est = Estimate(user_id=uid, number=num, name=name)
    db.add(est)
    db.commit()
    db.refresh(est)
    current_estimate_cache[uid] = est.id
    return est

def set_current_estimate(uid: int, est_id: int):
    current_estimate_cache[uid] = est_id

def next_estimate_number(db: Session, uid: int) -> int:
    row = db.execute(select(func.max(Estimate.number)).where(Estimate.user_id == uid)).scalar()
    return (row or 0) + 1

def enforce_retention(db: Session, uid: int):
    """Храним только последние RETENTION_LIMIT смет (по updated_at). Остальные удаляем с позициями."""
    ests: List[Estimate] = db.execute(
        select(Estimate).where(Estimate.user_id == uid).order_by(Estimate.updated_at.desc(), Estimate.id.desc())
    ).scalars().all()
    if len(ests) <= RETENTION_LIMIT:
        return
    to_keep = ests[:RETENTION_LIMIT]
    to_delete = ests[RETENTION_LIMIT:]
    keep_ids = {e.id for e in to_keep}
    del_ids = [e.id for e in to_delete]
    if not del_ids:
        return
    # Удалим позиции этих смет
    db.execute(
        delete(Position).where(Position.user_id == uid, Position.estimate_id.in_(del_ids))
    )
    # Удалим сами сметы
    db.execute(
        delete(Estimate).where(Estimate.user_id == uid, Estimate.id.in_(del_ids))
    )
    db.commit()
    # Если активная смета исчезла — переключим на самую свежую из оставшихся
    if uid in current_estimate_cache and current_estimate_cache[uid] not in keep_ids:
        fresh = to_keep[0]
        current_estimate_cache[uid] = fresh.id

def touch_estimate(db: Session, est: Estimate):
    est.updated_at = datetime.utcnow()
    db.commit()

def create_new_estimate_like(db: Session, uid: int, src_est: Estimate) -> Estimate:
    """Создаёт новую пустую смету с тем же названием, но с новым номером, делает её активной и применяет ретеншн."""
    num = next_estimate_number(db, uid)
    new_est = Estimate(user_id=uid, number=num, name=src_est.name)
    db.add(new_est)
    db.commit()
    db.refresh(new_est)
    set_current_estimate(uid, new_est.id)
    enforce_retention(db, uid)
    return new_est

# =========================
# Handlers
# =========================

START_TEXT = (
    "Привет! Я бот для расчёта смет.\n\n"
    "📌 Как пользоваться:\n"
    "— Нажми <b>«Начнём»</b>\n"
    "— Выбери категорию: <b>Материал</b> или <b>Работа</b>\n"
    "— Вводи строки:\n"
    "   🪵 Материал: <code>Гвозди, 1000, 20</code>  (кол-во, цена)\n"
    "   👷 Работа:   <code>Побелка, 150, 3000</code> (кол-во, цена)\n\n"
    "Сметы:\n"
    "/new [название] — новая смета и переключение на неё\n"
    "/estimates — список последних 5 смет\n"
    "/switch N — переключиться на смету №N\n\n"
    "Позиции (в рамках текущей сметы):\n"
    "/list — список позиций\n"
    "/delete ID — удалить позицию\n"
    "/edit ID [количество] [цена] — изменить\n"
    "/generate — Excel по текущей смете\n"
    "/clear — очистить позиции текущей сметы (с подтверждением)\n"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(START_TEXT, reply_markup=reply_kb_start(), parse_mode=ParseMode.HTML)

async def handle_begin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip().lower()
    if text == "начнём":
        user_category[update.effective_user.id] = None
        await update.message.reply_text("Выбери категорию: «Работа» или «Материал».", reply_markup=reply_kb_categories())
        return
    await handle_category(update, context)

async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip().lower()
    uid = update.effective_user.id
    if txt in ("работа", "материал"):
        cat = "Работа" if txt == "работа" else "Материал"
        user_category[uid] = cat
        example = "Гвозди, 1000, 20" if cat == "Материал" else "Побелка, 150, 3000"
        await update.message.reply_text(
            f"Активная категория: <b>{cat}</b> ✅\n"
            f"Введи позиции построчно. Пример: <code>{example}</code>\n"
            f"Когда закончишь — /generate",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_kb_categories(),
        )
    else:
        await update.message.reply_text("Нажми «Работа» или «Материал», либо /help.", reply_markup=reply_kb_categories())

# --- Estimates management ---

async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    parts = (update.message.text or "").strip().split(" ", 1)
    custom_name = parts[1].strip() if len(parts) > 1 else None

    with SessionLocal() as db:
        num = next_estimate_number(db, uid)
        est_name = custom_name or f"Смета №{num}"
        est = Estimate(user_id=uid, number=num, name=est_name)
        db.add(est)
        db.commit()
        db.refresh(est)
        set_current_estimate(uid, est.id)
        enforce_retention(db, uid)

    await update.message.reply_text(
        f"Создана и активирована <b>Смета №{est.number}</b> — {esc(est.name)}",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_kb_categories(),
    )

async def cmd_estimates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with SessionLocal() as db:
        ests = db.execute(
            select(Estimate)
            .where(Estimate.user_id == uid)
            .order_by(Estimate.updated_at.desc(), Estimate.id.desc())
            .limit(RETENTION_LIMIT)
        ).scalars().all()

        if not ests:
            await update.message.reply_text("У тебя пока нет смет. Создай: /new")
            return

        # Отправляем каждую смету отдельным сообщением с кнопкой "Обновить смету №N"
        for e in ests:
            total = db.execute(
                select(func.coalesce(func.sum((Position.qty * Position.price) * (1 + float(TAX_RATE))), 0))
                .where(Position.user_id == uid, Position.estimate_id == e.id)
            ).scalar() or 0.0
            count = db.execute(
                select(func.count(Position.id)).where(Position.user_id == uid, Position.estimate_id == e.id)
            ).scalar() or 0
            is_active = (uid in current_estimate_cache and current_estimate_cache[uid] == e.id)
            mark = " (активная)" if is_active else ""
            text_msg = (
                f"№{e.number}: {e.name}{mark}\n"
                f"Позиции: {count}  Итого (+6%): {short_money(Decimal(str(total)))}"
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"Обновить смету №{e.number}", callback_data=f"renew:{e.id}")
            ]])
            await update.message.reply_text(text_msg, reply_markup=kb)

async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = (update.message.text or "").split()
    if len(args) < 2:
        await update.message.reply_text("Использование: /switch N (номер сметы)")
        return
    try:
        num = int(args[1])
    except Exception:
        await update.message.reply_text("Номер сметы должен быть числом. Пример: /switch 3")
        return
    uid = update.effective_user.id
    with SessionLocal() as db:
        est = db.execute(select(Estimate).where(Estimate.user_id == uid, Estimate.number == num)).scalars().first()
        if not est:
            await update.message.reply_text(f"Смета №{num} не найдена. Посмотри /estimates")
            return
        set_current_estimate(uid, est.id)
        touch_estimate(db, est)
    await update.message.reply_text(
        f"Переключился на <b>Смета №{num}</b> — {esc(est.name)}",
        parse_mode=ParseMode.HTML,
        reply_markup=reply_kb_categories(),
    )

# --- Positions ---

async def add_line(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cat = user_category.get(uid)
    if not cat:
        await update.message.reply_text("Сначала выбери категорию: «Работа» или «Материал».", reply_markup=reply_kb_categories())
        return
    lines = [l.strip() for l in (update.message.text or "").split("\n")]
    lines = [l for l in lines if l]

    added = 0
    with SessionLocal() as db:
        est = get_current_estimate(db, uid)
        for line in lines:
            try:
                if cat == "Материал":
                    name, price, qty = parse_material_line(line)
                else:
                    name, price, qty = parse_work_line(line)

                # дубликаты: (estimate_id, category, name, price)
                existing = db.execute(
                    select(Position).where(
                        Position.user_id == uid,
                        Position.estimate_id == est.id,
                        Position.category == cat,
                        Position.name == name,
                        Position.price == price,
                    )
                ).scalars().first()
                if existing:
                    existing.qty = (existing.qty or Decimal("0")) + qty
                else:
                    db.add(Position(
                        user_id=uid,
                        estimate_id=est.id,
                        category=cat,
                        name=name,
                        qty=qty,
                        price=price,
                        unit="",
                    ))
                added += 1
            except Exception as e:
                await update.message.reply_text(
                    f"❗️Не удалось добавить строку:\n<code>{esc(line)}</code>\nПричина: {esc(e)}",
                    parse_mode=ParseMode.HTML
                )
        touch_estimate(db, est)

    await update.message.reply_text(f"Добавлено позиций: {added}. Посмотреть список: /list")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with SessionLocal() as db:
        est = get_current_estimate(db, uid)
        rows = db.execute(
            select(Position).where(Position.user_id == uid, Position.estimate_id == est.id).order_by(Position.category, Position.id)
        ).scalars().all()

    if not rows:
        await update.message.reply_text("В текущей смете пока пусто. Выбери категорию и добавь позиции.", reply_markup=reply_kb_categories())
        return

    out = [f"<b>{esc(est.name)}</b> (№{est.number})"]
    current_cat = None
    for r in rows:
        if r.category != current_cat:
            current_cat = r.category
            out.append(f"\n<b>{'Материалы и расходники' if current_cat=='Материал' else 'Работы'}</b>")
        # Жёстко показываем qty -> Кол-во, price -> Цена (фикс путаницы)
        out.append(
            f"#{r.id}: {esc(r.name)}\n"
            f"    Кол-во: {r.qty}  Цена: {short_money(r.price)}  Сумма(+6%): {short_money(r.sum_line_with_tax())}"
        )
    total = sum((r.sum_line_with_tax() for r in rows), Decimal("0"))
    out.append(f"\nИтого (+6%): <b>{short_money(total)}</b>")
    out.append(f"Наименований: <b>{len(rows)}</b>")

    await update.message.reply_text("\n".join(out), parse_mode=ParseMode.HTML)

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = (update.message.text or "").split()
    if len(args) < 2:
        await update.message.reply_text("Использование: /delete ID")
        return
    try:
        rid = int(args[1])
    except Exception:
        await update.message.reply_text("ID должен быть числом. Пример: /delete 12")
        return

    uid = update.effective_user.id
    with SessionLocal() as db:
        est = get_current_estimate(db, uid)
        row = db.execute(select(Position).where(Position.id == rid, Position.user_id == uid, Position.estimate_id == est.id)).scalars().first()
        if not row:
            await update.message.reply_text("Позиция не найдена в текущей смете.")
            return
        db.delete(row)
        touch_estimate(db, est)
    await update.message.reply_text(f"Удалено: #{rid}. Обновить список: /list")

async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    m = re.match(r"^/edit\s+(\d+)(.*)$", text, flags=re.IGNORECASE)
    if not m:
        await update.message.reply_text("Использование: /edit ID [количество] [цена]. Пример: /edit 12 200 350")
        return
    rid = int(m.group(1))
    tail = m.group(2).strip()

    qty: Optional[Decimal] = None
    price: Optional[Decimal] = None

    parts = [p for p in re.split(r"[, ]+", tail) if p != ""]
    try:
        if len(parts) == 1:
            qty = to_decimal(parts[0])
        elif len(parts) >= 2:
            if parts[0] != "-":
                qty = to_decimal(parts[0])
            if parts[1] != "-":
                price = to_decimal(parts[1])
    except Exception:
        await update.message.reply_text("Не удалось распознать количество/цену. Пример: /edit 12 200 350")
        return

    uid = update.effective_user.id
    with SessionLocal() as db:
        est = get_current_estimate(db, uid)
        row = db.execute(select(Position).where(Position.id == rid, Position.user_id == uid, Position.estimate_id == est.id)).scalars().first()
        if not row:
            await update.message.reply_text("Позиция не найдена в текущей смете.")
            return
        if qty is not None:
            row.qty = qty
        if price is not None:
            row.price = price

        # Merge duplicates внутри текущей сметы
        dup = db.execute(
            select(Position).where(
                Position.id != row.id,
                Position.user_id == uid,
                Position.estimate_id == est.id,
                Position.category == row.category,
                Position.name == row.name,
                Position.price == row.price,
            )
        ).scalars().first()
        if dup:
            row.qty = (row.qty or Decimal("0")) + (dup.qty or Decimal("0"))
            db.delete(dup)

        touch_estimate(db, est)

    await update.message.reply_text(f"Обновлено: #{rid}. Смотри /list")

# ======== /clear с подтверждением ========

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with SessionLocal() as db:
        est = get_current_estimate(db, uid)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Да", callback_data=f"clear_yes:{est.id}"),
            InlineKeyboardButton("Нет", callback_data=f"clear_no:{est.id}"),
        ]
    ])
    await update.message.reply_text(
        f"Вы точно хотите очистить позиции сметы {est.name} (№{est.number})?",
        reply_markup=kb
    )

# ----- Excel generation -----

THIN = Side(border_style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

def build_sheet(ws, title: str, rows: List[Position], is_work: bool):
    ws.title = title
    headers = (
        ["№", "Виды работ", "Кол-во (м2/мп/шт)", "Цена за ед.", "Сумма (+6%)"]
        if is_work else
        ["№", "Материалы и расходники", "Кол-во (шт/мп/м2)", "Цена", "Сумма (+6%)"]
    )
    ws.append(headers)

    # Header style
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="FFEFEFEF", end_color="FFEFEFEF", fill_type="solid")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER

    first_data_row = 2
    for idx, r in enumerate(rows, start=1):
        row_idx = first_data_row + idx - 1
        # жёсткое соответствие колонок: 3=qty, 4=price
        ws.cell(row=row_idx, column=1, value=idx)
        ws.cell(row=row_idx, column=2, value=r.name)
        ws.cell(row=row_idx, column=3, value=float(r.qty))
        ws.cell(row=row_idx, column=4, value=float(r.price))
        qty_col = get_column_letter(3)
        price_col = get_column_letter(4)
        sum_cell = ws.cell(row=row_idx, column=5)
        sum_cell.value = f"={qty_col}{row_idx}*{price_col}{row_idx}*{1 + float(TAX_RATE)}"

        for col in range(1, 6):
            c = ws.cell(row=row_idx, column=col)
            c.border = BORDER
            if col in (1, 3, 4, 5):
                c.alignment = Alignment(horizontal="center", vertical="center")
            else:
                c.alignment = Alignment(vertical="center")

    last_data_row = ws.max_row if ws.max_row >= first_data_row else first_data_row

    # Totals
    total_row = last_data_row + 1
    ws.cell(row=total_row, column=2, value="Итого")
    e_col = get_column_letter(5)
    ws.cell(row=total_row, column=5, value=f"=SUM({e_col}{first_data_row}:{e_col}{last_data_row})")
    ws.cell(row=total_row, column=2).font = Font(bold=True)
    ws.cell(row=total_row, column=5).font = Font(bold=True)
    ws.cell(row=total_row, column=2).alignment = Alignment(horizontal="right")
    ws.cell(row=total_row, column=2).border = BORDER
    ws.cell(row=total_row, column=5).border = BORDER

    count_row = total_row + 1
    ws.cell(row=count_row, column=2, value="Наименований")
    ws.cell(row=count_row, column=3, value=f"=COUNTA(B{first_data_row}:B{last_data_row})")
    ws.cell(row=count_row, column=2).font = Font(bold=True)
    ws.cell(row=count_row, column=3).font = Font(bold=True)
    ws.cell(row=count_row, column=2).alignment = Alignment(horizontal="right")
    ws.cell(row=count_row, column=2).border = BORDER
    ws.cell(row=count_row, column=3).border = BORDER

    # Column widths
    ws.column_dimensions[get_column_letter(1)].width = 6
    ws.column_dimensions[get_column_letter(2)].width = 60
    ws.column_dimensions[get_column_letter(3)].width = 18
    ws.column_dimensions[get_column_letter(4)].width = 14
    ws.column_dimensions[get_column_letter(5)].width = 18

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(5)}{last_data_row}"

def merge_duplicates_for_estimate(db: Session, uid: int, est_id: int) -> Tuple[List[Position], List[Position]]:
    """Собирает позиции текущей сметы, объединяя дубли по (category, name, price)."""
    rows = db.execute(
        select(
            Position.category,
            Position.name,
            Position.price,
            func.sum(Position.qty).label("qty"),
            func.min(Position.id).label("min_id"),
        ).where(Position.user_id == uid, Position.estimate_id == est_id)
         .group_by(Position.category, Position.name, Position.price)
         .order_by(Position.category, func.min(Position.id))
    ).all()

    materials: List[Position] = []
    works: List[Position] = []
    for cat, name, price, qty, min_id in rows:
        p = Position(
            id=int(min_id or 0),
            user_id=uid,
            estimate_id=est_id,
            category=cat,
            name=name,
            unit="",
            qty=Decimal(str(qty)),
            price=Decimal(str(price)),
            created_at=datetime.utcnow(),
        )
        (works if cat == "Работа" else materials).append(p)
    return materials, works

async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    with SessionLocal() as db:
        est = get_current_estimate(db, uid)
        materials, works = merge_duplicates_for_estimate(db, uid, est.id)
        if not materials and not works:
            await update.message.reply_text("Нет данных для отчёта в текущей смете. Добавь позиции и повтори /generate.")
            return

        wb = Workbook()
        ws1 = wb.active
        build_sheet(ws1, "Работы", works, is_work=True)
        ws2 = wb.create_sheet()
        build_sheet(ws2, "Материалы и расходники", materials, is_work=False)

        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)

    filename = f"estimate_{uid}_no{est.number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    await update.message.reply_document(
        document=InputFile(bio, filename=filename),
        caption=f"Готово: {est.name} (№{est.number}). Две вкладки: «Работы» и «Материалы и расходники». Сумма в строках включает +6%.",
    )

# ----- Callback buttons -----

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    uid = update.effective_user.id

    # Подтверждение обновления сметы
    if data.startswith("renew:"):
        est_id = int(data.split(":")[1])
        with SessionLocal() as db:
            est = db.get(Estimate, est_id)
            if not est or est.user_id != uid:
                await q.edit_message_text("Смета не найдена.")
                return
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Да", callback_data=f"renew_yes:{est.id}"),
                    InlineKeyboardButton("Нет", callback_data=f"renew_no:{est.id}"),
                ]
            ])
            await q.edit_message_text(
                f"Обновить смету №{est.number} — {esc(est.name)}?\n\n"
                f"Будет создана новая пустая смета со следующим номером, и она станет активной. Старая останется без изменений.",
                reply_markup=kb
            )
        return

    if data.startswith("renew_yes:"):
        est_id = int(data.split(":")[1])
        with SessionLocal() as db:
            src = db.get(Estimate, est_id)
            if not src or src.user_id != uid:
                await q.edit_message_text("Смета не найдена.")
                return
            new_est = create_new_estimate_like(db, uid, src)
            await q.edit_message_text(
                f"✅ Готово. Создана и активирована <b>Смета №{new_est.number}</b> — {esc(new_est.name)}.\n"
                f"Старая смета №{src.number} осталась без изменений.",
                parse_mode=ParseMode.HTML
            )
        return

    if data.startswith("renew_no:"):
        await q.edit_message_text("Отменено.")
        return

    # Подтверждение очистки сметы
    if data.startswith("clear_yes:"):
        est_id = int(data.split(":")[1])
        with SessionLocal() as db:
            est = db.get(Estimate, est_id)
            if not est or est.user_id != uid:
                await q.edit_message_text("Смета не найдена.")
                return
            db.execute(text("DELETE FROM positions WHERE user_id = :uid AND estimate_id = :eid"),
                       {"uid": uid, "eid": est.id})
            touch_estimate(db, est)
        await q.edit_message_text(f"Очищены позиции сметы {est.name} (№{est.number}).")
        return

    if data.startswith("clear_no:"):
        await q.edit_message_text("Отменено.")
        return

    # Удаление позиции из текущей сметы
    if data.startswith("del:"):
        rid = int(data.split(":")[1])
        with SessionLocal() as db:
            est = get_current_estimate(db, uid)
            row = db.execute(
                select(Position).where(Position.id == rid, Position.user_id == uid, Position.estimate_id == est.id)
            ).scalars().first()
            if not row:
                await q.edit_message_text("Позиция не найдена в текущей смете.")
                return
            db.delete(row)
            touch_estimate(db, est)
        await q.edit_message_text(f"Удалено: #{rid}. Обновить список: /list")
        return

    # Подсказка по редактированию
    if data.startswith("edit:"):
        rid = int(data.split(":")[1])
        await q.edit_message_text(
            f"Чтобы изменить: отправь команду\n<code>/edit {rid} НОВОЕ_КОЛ НОВАЯ_ЦЕНА</code>",
            parse_mode=ParseMode.HTML
        )
        return

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT, parse_mode=ParseMode.HTML, reply_markup=reply_kb_start())

# =========================
# App bootstrap
# =========================

def build_app():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))

    # Estimates
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("estimates", cmd_estimates))
    app.add_handler(CommandHandler("switch", cmd_switch))

    # Positions & files
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("clear", cmd_clear))  # теперь с подтверждением

    # Buttons & categories (регистронезависимо)
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^начнём$"), handle_begin))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^(работа|материал)$"), handle_category))

    # Free text lines for positions (current estimate)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_line))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(on_callback))

    return app

def main():
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
