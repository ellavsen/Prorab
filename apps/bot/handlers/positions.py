"""Хендлеры позиций: ввод строк, /list, /delete, /edit, /clear."""

import re
from dataclasses import replace
from decimal import Decimal

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from smeta_core import (
    UNITS,
    AmbiguousLine,
    Category,
    default_unit,
    merge_duplicates,
    normalize_unit,
    parse_position_line,
    parse_price,
    parse_quantity,
    to_kop,
    to_milli,
)
from smeta_storage import current_estimate, positions, touch_estimate, user_state

from ..database import SessionLocal
from ..keyboards import categories_keyboard, confirm_keyboard
from ..texts import (
    CATEGORY_PROMPT,
    EMPTY_ESTIMATE,
    esc,
    render_estimate,
    render_units_substituted,
)
from . import ai, stepwise

EDIT_PATTERN = re.compile(r"^/edit\s+(\d+)(.*)$", flags=re.IGNORECASE)


async def on_text(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Единственная точка входа для свободного текста.

    Если начат пошаговый ввод — текст идёт в его текущий шаг; иначе трактуется
    как строки позиций. Состояние читается из базы, поэтому рестарт процесса
    посреди диалога ничего не ломает.
    """
    uid = update.effective_user.id
    with SessionLocal() as db:
        state = user_state(db, uid)
        if not state.category:
            await update.message.reply_text(CATEGORY_PROMPT, reply_markup=categories_keyboard())
            return

        category = Category(state.category)
        if state.draft_step:
            await stepwise.handle_text_step(
                update.message, db, uid, category, update.message.text or ""
            )
            return
        await _add_bulk(update, db, uid, category)


async def _add_bulk(update: Update, db, uid: int, category: Category) -> None:
    text = update.message.text or ""
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    added = 0
    substituted: dict[str, list[str]] = {}
    ambiguous: list[AmbiguousLine] = []
    failed: list[tuple[str, ValueError]] = []
    estimate = current_estimate(db, uid)

    for line in lines:
        try:
            position = parse_position_line(line, category)
        except AmbiguousLine as error:
            ambiguous.append(error)
            continue
        except ValueError as error:
            failed.append((line, error))
            continue

        if not position.unit:
            unit = default_unit(category)
            position = replace(position, unit=unit)
            substituted.setdefault(unit, []).append(position.name)
        positions.add(db, uid, estimate.id, position)
        added += 1

    # Строгий формат не дал ничего — значит, это живая речь, а не список.
    # Отвечать ошибкой на каждую строку тут бесполезно: пусть разбирает модель.
    if failed and not added and not ambiguous:
        await ai.demo_note(update.message)
        await ai.extract_and_offer(update.message, db, uid, text)
        return

    touch_estimate(db, estimate)
    for line, error in failed:
        await update.message.reply_text(
            f"❗️Не удалось добавить строку:\n<code>{esc(line)}</code>\n"
            f"Причина: {esc(error)}",
            parse_mode=ParseMode.HTML,
        )

    for unit, names in substituted.items():
        await update.message.reply_text(render_units_substituted(names, unit))
    if added:
        await update.message.reply_text(f"Добавлено позиций: {added}. Посмотреть список: /list")

    if ambiguous:
        if len(ambiguous) > 1:
            await update.message.reply_text(
                f"Неоднозначных строк: {len(ambiguous)}. Разберём по одной."
            )
        await stepwise.offer_readings(update.message, db, uid, ambiguous[0])


async def cmd_unit(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unit ID ед — исправить единицу уже введённой позиции."""
    args = (update.message.text or "").split()
    if len(args) < 3:
        await update.message.reply_text(
            "Использование: /unit ID единица. Пример: <code>/unit 12 м2</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        position_id = int(args[1])
    except ValueError:
        await update.message.reply_text("ID должен быть числом. Пример: /unit 12 м2")
        return

    # Единица не участвует в арифметике, поэтому незнакомая — не ошибка:
    # печатаем сказанное, канон остаётся пустым (ADR-015).
    spoken = " ".join(args[2:])
    unit = normalize_unit(spoken)

    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        row = positions.get(db, uid, estimate.id, position_id)
        if row is None:
            await update.message.reply_text("Позиция не найдена в текущей смете.")
            return
        row.unit = unit
        row.unit_spoken = spoken
        touch_estimate(db, estimate)
        name = row.name

    note = "" if unit else (
        f"\nВ справочнике такой единицы нет — в отчёт пойдёт «{esc(spoken)}», "
        f"а для аналитики она останется без канона. Канонические: {', '.join(UNITS)}"
    )
    await update.message.reply_text(
        f"#{position_id} {esc(name)} — теперь в «{esc(spoken)}».{note}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_list(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        rows = positions.load(db, uid, estimate.id)
        totals = positions.totals(db, uid, estimate)

    if not rows:
        await update.message.reply_text(EMPTY_ESTIMATE, reply_markup=categories_keyboard())
        return

    await update.message.reply_text(
        render_estimate(estimate, rows, totals), parse_mode=ParseMode.HTML
    )


async def cmd_delete(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    args = (update.message.text or "").split()
    if len(args) < 2:
        await update.message.reply_text("Использование: /delete ID")
        return
    try:
        position_id = int(args[1])
    except ValueError:
        await update.message.reply_text("ID должен быть числом. Пример: /delete 12")
        return

    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        row = positions.get(db, uid, estimate.id, position_id)
        if row is None:
            await update.message.reply_text("Позиция не найдена в текущей смете.")
            return
        db.delete(row)
        touch_estimate(db, estimate)
    await update.message.reply_text(f"Удалено: #{position_id}. Обновить список: /list")


def _parse_edit_tail(tail: str) -> tuple[Decimal | None, Decimal | None]:
    parts = [part for part in re.split(r"[, ]+", tail) if part]
    quantity = price = None
    if len(parts) == 1:
        quantity = parse_quantity(parts[0])
    elif len(parts) >= 2:
        if parts[0] != "-":
            quantity = parse_quantity(parts[0])
        if parts[1] != "-":
            price = parse_price(parts[1])
    return quantity, price


async def cmd_edit(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    match = EDIT_PATTERN.match((update.message.text or "").strip())
    if not match:
        await update.message.reply_text(
            "Использование: /edit ID [количество] [цена]. Пример: /edit 12 200 350"
        )
        return
    position_id = int(match.group(1))

    try:
        quantity, price = _parse_edit_tail(match.group(2).strip())
    except ValueError as error:
        await update.message.reply_text(
            f"{esc(error)}\nПример: <code>/edit 12 200 350</code>", parse_mode=ParseMode.HTML
        )
        return

    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        row = positions.get(db, uid, estimate.id, position_id)
        if row is None:
            await update.message.reply_text("Позиция не найдена в текущей смете.")
            return
        if quantity is not None:
            row.qty_milli = to_milli(quantity)
        if price is not None:
            row.price_kop = to_kop(price)

        twin = positions.find_twin(db, uid, estimate.id, row.to_domain(), exclude_id=row.id)
        if twin is not None:
            try:
                merged = merge_duplicates([row.to_domain(), twin.to_domain()])[0]
            except ValueError as error:
                await update.message.reply_text(str(error))
                return
            row.qty_milli = to_milli(merged.qty)
            db.delete(twin)
        touch_estimate(db, estimate)

    await update.message.reply_text(f"Обновлено: #{position_id}. Смотри /list")


async def cmd_clear(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
    await update.message.reply_text(
        f"Вы точно хотите очистить позиции сметы {estimate.name} (№{estimate.number})?",
        reply_markup=confirm_keyboard("clear", estimate.id),
    )
