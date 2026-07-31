"""Пошаговый ввод позиции — путь по умолчанию (ADR-010).

Черновик живёт в таблице user_state, а не в памяти процесса: рестарт посреди
ввода не должен стоить пользователю набранного. В смету ничего не попадает без
предпросмотра с подтверждением.
"""

from telegram import Message, Update
from telegram.constants import ParseMode

from smeta_core import (
    AmbiguousLine,
    Category,
    PositionData,
    calculate_estimate,
    default_unit,
    parse_position_line,
    parse_price,
    parse_quantity,
    split_qty_unit,
    to_kop,
    to_milli,
)
from smeta_storage import (
    clear_draft,
    current_estimate,
    positions,
    touch_estimate,
    update_draft,
    user_state,
)

from ..database import SessionLocal
from ..keyboards import categories_keyboard, draft_keyboard, readings_keyboard, units_keyboard
from ..texts import (
    ASK_NAME,
    ASK_PRICE,
    ASK_QTY,
    ASK_UNIT,
    CATEGORY_PROMPT,
    DRAFT_CANCELLED,
    esc,
    render_draft,
    render_readings,
)

NAME, QTY, UNIT, PRICE, CONFIRM, AMBIGUOUS = (
    "name", "qty", "unit", "price", "confirm", "ambiguous"
)


async def start_draft(message: Message, db, uid: int) -> None:
    clear_draft(db, uid)
    update_draft(db, uid, draft_step=NAME)
    await message.reply_text(ASK_NAME)


def draft_position(state, category: Category) -> PositionData:
    return PositionData(
        category=category,
        name=state.draft_name,
        qty=state.draft_qty,
        price=state.draft_price,
        unit=state.draft_unit or "",
    )


def _line_total(db, uid: int, position: PositionData):
    estimate = current_estimate(db, uid)
    totals = calculate_estimate(
        [position], estimate.markup_work_rate, estimate.markup_material_rate
    )
    return totals.lines[0].total


async def _show_preview(message: Message, db, uid: int, category: Category) -> None:
    state = user_state(db, uid)
    position = draft_position(state, category)
    update_draft(db, uid, draft_step=CONFIRM)
    await message.reply_text(
        render_draft(state, _line_total(db, uid, position)),
        parse_mode=ParseMode.HTML,
        reply_markup=draft_keyboard(),
    )


async def handle_text_step(message: Message, db, uid: int, category: Category, text: str) -> None:
    """Шаги наименования, количества и цены. Единицу выбирают кнопкой."""
    state = user_state(db, uid)
    step = state.draft_step

    if step == NAME:
        update_draft(db, uid, draft_name=text.strip()[:200], draft_step=QTY)
        await message.reply_text(ASK_QTY, parse_mode=ParseMode.HTML)
        return

    if step == QTY:
        # Количество может нести единицу: «150 м2» — тогда шаг единицы пропускаем.
        raw_qty, unit = split_qty_unit(text)
        try:
            quantity = parse_quantity(raw_qty)
        except ValueError as error:
            await message.reply_text(f"{esc(error)}\nПопробуй ещё раз.", parse_mode=ParseMode.HTML)
            return
        if unit:
            update_draft(db, uid, draft_qty_milli=to_milli(quantity), draft_unit=unit,
                         draft_step=PRICE)
            await message.reply_text(f"Единица: {unit}. {ASK_PRICE}")
        else:
            update_draft(db, uid, draft_qty_milli=to_milli(quantity), draft_step=UNIT)
            await message.reply_text(ASK_UNIT, reply_markup=units_keyboard())
        return

    if step == PRICE:
        try:
            price = parse_price(text)
        except ValueError as error:
            await message.reply_text(f"{esc(error)}\nПопробуй ещё раз.", parse_mode=ParseMode.HTML)
            return
        update_draft(db, uid, draft_price_kop=to_kop(price))
        await _show_preview(message, db, uid, category)
        return

    # На шаге выбора единицы или подтверждения ждём кнопку, а не текст.
    await message.reply_text("Нажми кнопку под сообщением выше.")


async def handle_unit_choice(query, db, uid: int, value: str) -> None:
    state = user_state(db, uid)
    category = Category(state.category or Category.MATERIAL)
    unit = default_unit(category) if value == "-" else value
    update_draft(db, uid, draft_unit=unit, draft_step=PRICE)

    note = " (подставлена по категории)" if value == "-" else ""
    await query.edit_message_text(f"Единица: {unit}{note}. {ASK_PRICE}")


async def handle_draft_action(query, db, uid: int, action: str) -> None:
    state = user_state(db, uid)
    category = Category(state.category or Category.MATERIAL)

    if action == "cancel":
        clear_draft(db, uid)
        await query.edit_message_text(DRAFT_CANCELLED)
        return

    if action == "restart":
        clear_draft(db, uid)
        update_draft(db, uid, draft_step=NAME)
        await query.edit_message_text(ASK_NAME)
        return

    estimate = current_estimate(db, uid)
    positions.add(db, uid, estimate.id, draft_position(state, category))
    touch_estimate(db, estimate)
    name = state.draft_name

    clear_draft(db, uid)
    update_draft(db, uid, draft_step=NAME)
    await query.edit_message_text(f"Добавлено: {esc(name)}")
    await query.message.reply_text(f"{ASK_NAME} Закончить — /list")


async def offer_readings(message: Message, db, uid: int, error: AmbiguousLine) -> None:
    """Неоднозначную строку не разбираем молча — показываем оба прочтения."""
    update_draft(db, uid, draft_step=AMBIGUOUS, pending_line=error.line[:512])
    await message.reply_text(
        render_readings(error.line, error.plain, error.merged),
        parse_mode=ParseMode.HTML,
        reply_markup=readings_keyboard(),
    )


async def handle_reading_choice(query, db, uid: int, which: str) -> None:
    state = user_state(db, uid)
    line, category = state.pending_line, Category(state.category or Category.MATERIAL)
    clear_draft(db, uid)

    if which == "cancel" or not line:
        await query.edit_message_text("Строка пропущена.")
        return

    try:
        parse_position_line(line, category)
    except AmbiguousLine as error:
        chosen = error.plain if which == "plain" else error.merged
    else:
        await query.edit_message_text("Строка больше не неоднозначна, добавь её заново.")
        return

    estimate = current_estimate(db, uid)
    positions.add(db, uid, estimate.id, chosen)
    touch_estimate(db, estimate)
    await query.edit_message_text(
        f"Добавлено: {esc(chosen.name)}, {chosen.qty} × {chosen.price}"
    )


async def cmd_add(update: Update, _context) -> None:
    """Команда /add — явный вход в пошаговый ввод."""
    uid = update.effective_user.id
    with SessionLocal() as db:
        if not user_state(db, uid).category:
            await update.message.reply_text(CATEGORY_PROMPT, reply_markup=categories_keyboard())
            return
        await start_draft(update.message, db, uid)
