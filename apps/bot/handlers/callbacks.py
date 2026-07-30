"""Инлайн-кнопки. Обрабатывается ровно то, что отправляется из keyboards.py."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from smeta_storage import Estimate, create_new_estimate_like, positions, touch_estimate

from ..database import SessionLocal
from ..keyboards import confirm_keyboard
from ..texts import esc

NOT_FOUND = "Смета не найдена."
CANCELLED = "Отменено."


def _owned_estimate(db, uid: int, data: str) -> Estimate | None:
    estimate = db.get(Estimate, int(data.split(":")[1]))
    return estimate if estimate is not None and estimate.user_id == uid else None


async def on_callback(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    uid = update.effective_user.id

    if data.startswith(("renew_no:", "clear_no:")):
        await query.edit_message_text(CANCELLED)
        return

    with SessionLocal() as db:
        estimate = _owned_estimate(db, uid, data)
        if estimate is None:
            await query.edit_message_text(NOT_FOUND)
            return

        if data.startswith("renew:"):
            await query.edit_message_text(
                f"Обновить смету №{estimate.number} — {esc(estimate.name)}?\n\n"
                f"Будет создана новая пустая смета со следующим номером, и она станет "
                f"активной. Старая останется без изменений.",
                reply_markup=confirm_keyboard("renew", estimate.id),
                parse_mode=ParseMode.HTML,
            )
            return

        if data.startswith("renew_yes:"):
            created = create_new_estimate_like(db, uid, estimate)
            await query.edit_message_text(
                f"✅ Готово. Создана и активирована <b>Смета №{created.number}</b> — "
                f"{esc(created.name)}.\n"
                f"Старая смета №{estimate.number} осталась без изменений.",
                parse_mode=ParseMode.HTML,
            )
            return

        if data.startswith("clear_yes:"):
            positions.clear(db, uid, estimate.id)
            touch_estimate(db, estimate)
            await query.edit_message_text(
                f"Очищены позиции сметы {estimate.name} (№{estimate.number})."
            )
            return
