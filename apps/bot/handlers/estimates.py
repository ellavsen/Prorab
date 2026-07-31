"""Хендлеры сметы: старт, категория, /new, /estimates, /switch."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from smeta_core import parse_rate, to_bp
from smeta_storage import (
    create_estimate,
    current_estimate,
    enforce_retention,
    find_by_number,
    list_estimates,
    positions,
    set_category,
    set_current_estimate,
    set_rates,
    touch_estimate,
    user_state,
)

from ..database import SessionLocal
from ..keyboards import categories_keyboard, mode_keyboard, renew_keyboard, start_keyboard
from ..texts import START_TEXT, esc, render_rates, render_summary


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

    await update.message.reply_text(
        f"Активная категория: <b>{category}</b> ✅\nКак вводим?",
        parse_mode=ParseMode.HTML,
        reply_markup=mode_keyboard(),
    )


RATE_TARGETS = {
    "работы": "work",
    "работа": "work",
    "материалы": "material",
    "материал": "material",
}


async def cmd_rate(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """/rate 6 — обе ставки; /rate работы 10 — только работы; /rate — показать.

    Меняет ставку ТОЛЬКО активной сметы: ставка — часть документа, и уже
    выставленные сметы от этого не меняются (ADR-003).
    """
    args = (update.message.text or "").split()[1:]
    uid = update.effective_user.id

    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        if not args:
            await update.message.reply_text(
                render_rates(estimate, positions.totals(db, uid, estimate)),
                parse_mode=ParseMode.HTML,
            )
            return

        target = "both"
        if args[0].lower() in RATE_TARGETS:
            target = RATE_TARGETS[args[0].lower()]
            args = args[1:]
        if not args:
            await update.message.reply_text("Не указано значение. Пример: /rate работы 10")
            return

        try:
            rate_bp = to_bp(parse_rate(args[0]))
        except ValueError as error:
            await update.message.reply_text(
                f"{esc(error)}\nПример: <code>/rate 6</code>", parse_mode=ParseMode.HTML
            )
            return

        set_rates(
            db, estimate,
            work_bp=rate_bp if target in ("both", "work") else estimate.markup_work_bp,
            material_bp=rate_bp if target in ("both", "material") else estimate.markup_material_bp,
        )
        await update.message.reply_text(
            render_rates(estimate, positions.totals(db, uid, estimate)),
            parse_mode=ParseMode.HTML,
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
