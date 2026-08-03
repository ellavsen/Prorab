"""Отправка сметы заказчику: заморозка, ссылка, ревизия, отзыв.

/send делает два действия одной командой, и порядок важен: сначала смета
замораживается (money.md И3), потом на неё выдаётся ссылка. Ссылки на черновик
не бывает по построению — issue() её не выдаст.

/revise здесь не для полноты набора. Машина состояний появилась в ядре раньше
бота, и до сих пор перевести смету в SENT было нечем — значит, охрана не
срабатывала ни разу. С /send она срабатывает, и без /revise первая же
отправка оставила бы человека с документом, который нельзя ни изменить, ни
продолжить. FROZEN_HINT обещает эту команду; здесь она появляется.
"""

from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from smeta_core import format_money
from smeta_export import spell_date
from smeta_storage import (
    StateError,
    current_estimate,
    revise,
    send,
    set_current_estimate,
    share,
    verified_totals,
)

from ..config import share_base_url
from ..database import SessionLocal
from ..keyboards import confirm_keyboard
from ..texts import esc

SENT = (
    "✅ <b>Смета №{number} (ред. {version})</b> отправлена.\n"
    "Итог {total} ₽ — дальше этот документ не меняется.\n\n"
    "Ссылка для заказчика:\n{url}\n\n"
    "⚠️ Страница увидит название сметы — проверьте, что там нет лишнего.\n"
    "Ссылка действует {days} дней. Сохраните это сообщение: в базе лежит только "
    "отпечаток ссылки, показать её повторно неоткуда.\n"
    "Правка — /revise, отзыв — /revoke."
)

REVISED = (
    "📝 <b>Смета №{number}, ред. {version}</b> — черновик с копией позиций.\n"
    "Ред. {previous} остаётся действующей у заказчика, пока новую не отправят: "
    "/send"
)

NO_LINK = "На эту смету ссылки нет. Отправьте её заказчику: /send"
REVOKED = "Ссылка отозвана. Заказчик увидит «Ссылка недоступна»."
REVOKE_APPROVED = (
    "Смету №{number} (ред. {version}) заказчик уже согласовал {on}.\n"
    "Отозвать ссылку — значит закрыть согласованный документ. Точно?"
)


def _moment(value: datetime | None) -> str:
    """Время хранится наивным UTC, поэтому оно так и подписано (models.utcnow)."""
    return "—" if value is None else f"{spell_date(value.date())}, {value:%H:%M} UTC"


async def cmd_send(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        try:
            send(db, estimate)
            token = share.issue(db, estimate)
        except StateError as error:
            await update.message.reply_text(str(error))
            return
        totals = verified_totals(db, estimate)
        number, version = estimate.number, estimate.version

    await update.message.reply_text(
        SENT.format(
            number=number,
            version=version,
            total=format_money(totals.total),
            url=f"{share_base_url()}/e/{token}",
            days=share.DEFAULT_TTL_DAYS,
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_revise(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Новая версия с копией позиций. Старая продолжает действовать у заказчика."""
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        try:
            revision = revise(db, estimate)
        except StateError as error:
            await update.message.reply_text(str(error))
            return
        set_current_estimate(db, uid, revision.id)
        number, version, previous = revision.number, revision.version, estimate.version

    await update.message.reply_text(
        REVISED.format(number=number, version=version, previous=previous),
        parse_mode=ParseMode.HTML,
    )


async def cmd_link(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Состояние ссылки. Самой ссылки здесь нет — её хранит только заказчик."""
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        link = share.latest_for(db, estimate.id)
        if link is None:
            await update.message.reply_text(NO_LINK)
            return
        lines = [
            f"<b>Смета №{estimate.number} (ред. {estimate.version})</b> — "
            f"{esc(estimate.name)}",
            f"Открыта: {_moment(link.first_viewed_at)}",
            f"Последний раз: {_moment(link.last_viewed_at)}",
        ]
        if link.approved_at is not None:
            lines.append(f"✅ Согласована: {_moment(link.approved_at)}, бессрочно")
        elif link.revoked_at is not None:
            lines.append(f"Отозвана: {_moment(link.revoked_at)}")
        elif link.expires_at is not None:
            lines.append(f"Действует до: {spell_date(link.expires_at.date())}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_revoke(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Согласованную ссылку отзываем только с подтверждением, как /clear."""
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        link = share.latest_for(db, estimate.id)
        if link is None or link.revoked_at is not None:
            await update.message.reply_text(NO_LINK)
            return
        if link.approved_at is None:
            share.revoke(db, link)
            await update.message.reply_text(REVOKED)
            return
        question = REVOKE_APPROVED.format(
            number=estimate.number,
            version=estimate.version,
            on=spell_date(link.approved_at.date()),
        )
        keyboard = confirm_keyboard("revoke", estimate.id)

    await update.message.reply_text(question, reply_markup=keyboard)
