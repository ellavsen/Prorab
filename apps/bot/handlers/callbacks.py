"""Инлайн-кнопки. Обрабатывается ровно то, что отправляется из keyboards.py."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from smeta_core import RateBase
from smeta_storage import (
    Estimate,
    create_new_estimate_like,
    current_estimate,
    positions,
    set_rate_base,
    share,
    touch_estimate,
)

from ..config import share_base_url
from ..database import SessionLocal
from ..keyboards import basis_choice_keyboard, confirm_keyboard
from ..texts import (
    BASIS_SET,
    BULK_HINT,
    STALE_BUTTON,
    basis_effect,
    basis_example,
    basis_question,
    esc,
    markup_caption,
)
from . import preview, stepwise
from .share import RELINKED, REVOKED, link_block

NOT_FOUND = "Смета не найдена."
CANCELLED = "Отменено."


def _owned_estimate(db, uid: int, data: str) -> Estimate | None:
    """Смета из callback_data — только если она принадлежит нажавшему.

    callback_data приходит от клиента и содержит id, поэтому проверяется и то,
    и другое: что это вообще число (кнопка могла остаться от другой версии
    бота) и что смета чужому не отдаётся. uid берётся из апдейта, а не из
    данных кнопки, — подменить его нажимающий не может.
    """
    _, _, raw = data.partition(":")
    if not raw.isdigit():
        return None
    estimate = db.get(Estimate, int(raw))
    return estimate if estimate is not None and estimate.user_id == uid else None


async def _basis(query, db, uid: int, value: str) -> None:
    """Кнопки про основание процента: спросить и выбрать.

    Работает с активной сметой, а не с id из кнопки: основание — свойство того,
    что человек редактирует сейчас, и кнопка из прошлого разговора не должна
    менять деньги в смете, которую он с тех пор переключил.
    """
    estimate = current_estimate(db, uid)
    if value == "ask":
        await query.edit_message_text(
            basis_question(first=False), parse_mode=ParseMode.HTML,
            reply_markup=basis_choice_keyboard(
                basis_example(RateBase.COST), basis_example(RateBase.PRICE)
            ),
        )
        return

    if value not in tuple(RateBase):
        await query.edit_message_text(STALE_BUTTON)
        return

    set_rate_base(db, estimate, value)
    await query.edit_message_text(
        BASIS_SET.format(
            caption=markup_caption(estimate), effect=basis_effect(value)
        ),
        parse_mode=ParseMode.HTML,
    )


async def on_callback(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    uid = update.effective_user.id

    if data.startswith(("renew_no:", "clear_no:", "revoke_no:", "relink_no:")):
        await query.edit_message_text(CANCELLED)
        return

    if data.startswith("basis:"):
        _, _, value = data.partition(":")
        with SessionLocal() as db:
            await _basis(query, db, uid, value)
        return

    # Пошаговый ввод, разбор неоднозначных строк и предпросмотр распознанной
    # пачки — каждый работает со своим состоянием.
    if data.startswith(("mode:", "unit:", "draft:", "pick:", "ai:")):
        prefix, _, value = data.partition(":")
        with SessionLocal() as db:
            if prefix == "mode":
                if value == "step":
                    await query.edit_message_text("Добавляем по шагам.")
                    await stepwise.start_draft(query.message, db, uid)
                else:
                    await query.edit_message_text(BULK_HINT, parse_mode=ParseMode.HTML)
            elif prefix == "unit":
                await stepwise.handle_unit_choice(query, db, uid, value)
            elif prefix == "draft":
                await stepwise.handle_draft_action(query, db, uid, value)
            elif prefix == "ai":
                await preview.handle_action(query, db, uid, value)
            else:
                await stepwise.handle_reading_choice(query, db, uid, value)
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

        if data.startswith("revoke_yes:"):
            link = share.latest_for(db, estimate.id)
            if link is not None:
                share.revoke(db, link)
            await query.edit_message_text(REVOKED)
            return

        if data.startswith("relink_yes:"):
            token = share.reissue(db, estimate)
            await query.edit_message_text(
                RELINKED.format(
                    number=estimate.number,
                    version=estimate.version,
                    link=link_block(
                        f"{share_base_url()}/e/{token}",
                        estimate.approved_at is not None,
                    ),
                ),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return

        if data.startswith("clear_yes:"):
            positions.clear(db, uid, estimate.id)
            touch_estimate(db, estimate)
            await query.edit_message_text(
                f"Очищены позиции сметы {estimate.name} (№{estimate.number})."
            )
            return

    # Сюда попадает кнопка, которой этот бот больше не отправляет: сообщение
    # из прошлой версии или из очень старого разговора. Молчание в ответ
    # человек читает как поломку и жмёт ещё несколько раз.
    await query.edit_message_text(STALE_BUTTON)
