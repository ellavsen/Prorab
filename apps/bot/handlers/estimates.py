"""Хендлеры сметы: старт, категория, /new, /estimates, /switch."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from smeta_storage import (
    create_estimate,
    enforce_retention,
    find_by_number,
    list_estimates,
    positions,
    set_category,
    set_current_estimate,
    touch_estimate,
    user_state,
)

from ..database import SessionLocal
from ..keyboards import categories_keyboard, renew_keyboard, start_keyboard
from ..texts import START_TEXT, esc, render_summary


async def start(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        START_TEXT, reply_markup=start_keyboard(), parse_mode=ParseMode.HTML
    )


async def help_command(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        START_TEXT, parse_mode=ParseMode.HTML, reply_markup=start_keyboard()
    )


async def handle_begin(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    with SessionLocal() as db:
        set_category(db, update.effective_user.id, None)
    await update.message.reply_text(
        "Выбери категорию: «Работа» или «Материал».", reply_markup=categories_keyboard()
    )


async def handle_category(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip().lower()
    category = "Работа" if text == "работа" else "Материал"
    with SessionLocal() as db:
        set_category(db, update.effective_user.id, category)

    example = "Гвозди, 1000 шт, 20" if category == "Материал" else "Побелка, 150 м2, 3000"
    await update.message.reply_text(
        f"Активная категория: <b>{category}</b> ✅\n"
        f"Введи позиции построчно. Пример: <code>{example}</code>\n"
        f"Когда закончишь — /generate",
        parse_mode=ParseMode.HTML,
        reply_markup=categories_keyboard(),
    )


async def cmd_new(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    parts = (update.message.text or "").strip().split(" ", 1)
    custom_name = parts[1].strip() if len(parts) > 1 else None

    with SessionLocal() as db:
        estimate = create_estimate(db, uid, name=custom_name)
        set_current_estimate(db, uid, estimate.id)
        enforce_retention(db, uid)

    await update.message.reply_text(
        f"Создана и активирована <b>Смета №{estimate.number}</b> — {esc(estimate.name)}",
        parse_mode=ParseMode.HTML,
        reply_markup=categories_keyboard(),
    )


async def cmd_estimates(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimates = list_estimates(db, uid)
        if not estimates:
            await update.message.reply_text("У тебя пока нет смет. Создай: /new")
            return

        active_id = user_state(db, uid).current_estimate_id
        # Итог считает домен. Денежных агрегатов в SQL нет — они дают другой
        # ответ, чем /list и Excel (ADR-002).
        summaries = [
            (estimate, positions.totals(db, uid, estimate), estimate.id == active_id)
            for estimate in estimates
        ]

    for estimate, totals, is_active in summaries:
        await update.message.reply_text(
            render_summary(estimate, totals, is_active),
            reply_markup=renew_keyboard(estimate.id, estimate.number),
        )


async def cmd_switch(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    args = (update.message.text or "").split()
    if len(args) < 2:
        await update.message.reply_text("Использование: /switch N (номер сметы)")
        return
    try:
        number = int(args[1])
    except ValueError:
        await update.message.reply_text("Номер сметы должен быть числом. Пример: /switch 3")
        return

    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = find_by_number(db, uid, number)
        if estimate is None:
            await update.message.reply_text(f"Смета №{number} не найдена. Посмотри /estimates")
            return
        set_current_estimate(db, uid, estimate.id)
        touch_estimate(db, estimate)

    await update.message.reply_text(
        f"Переключился на <b>Смета №{number}</b> — {esc(estimate.name)}",
        parse_mode=ParseMode.HTML,
        reply_markup=categories_keyboard(),
    )
