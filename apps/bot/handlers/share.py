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
from ..texts import describe_version, esc

LINK_BLOCK = (
    "Ссылка для заказчика:\n{url}\n\n"
    "⚠️ Страница увидит название сметы — проверьте, что там нет лишнего.\n"
    "{life} Сохраните это сообщение: в базе лежит только отпечаток ссылки, "
    "показать её повторно неоткуда — но можно выдать новую: /relink."
)
FOREVER = "Смета согласована, поэтому ссылка бессрочна."
UNTIL = "Ссылка действует {days} дней."

SENT = (
    "✅ <b>Смета №{number} (ред. {version})</b> отправлена.\n"
    "Итог {total} ₽ — дальше этот документ не меняется.\n\n"
    "{link}\n"
    "Правка — /revise, отзыв — /revoke."
)

RELINKED = "🔗 <b>Смета №{number} (ред. {version})</b> — новая ссылка.\n\n{link}"

RELINK_ASK = (
    "Выдать новую ссылку на смету №{number} ({version})?\n\n"
    "Старая перестанет открываться сразу же. У заказчика на руках останется "
    "нерабочий адрес — новый придётся прислать ему самому.{approved}"
)
RELINK_APPROVED = "\n\nСогласование сохранится: согласована смета, а не ссылка."
RELINK_DRAFT = "Черновик заказчику не отдают. Сначала отправьте: /send"

REVISED = (
    "📝 <b>Смета №{number}, ред. {version}</b> — черновик с копией позиций.\n"
    "Ред. {previous} остаётся действующей у заказчика, пока новую не отправят: "
    "/send"
)

NO_LINK = "Действующей ссылки на эту смету нет. Выдать новую: /relink"
REVOKED = "Ссылка отозвана. Заказчик увидит «Ссылка недоступна»."
REVOKE_APPROVED = (
    "Смету №{number} (ред. {version}) заказчик уже согласовал {on}.\n"
    "Отозвать ссылку — значит закрыть согласованный документ. Точно?"
)


def _moment(value: datetime | None) -> str:
    """Время хранится наивным UTC, поэтому оно так и подписано (models.utcnow)."""
    return "—" if value is None else f"{spell_date(value.date())}, {value:%H:%M} UTC"


def link_block(url: str, approved: bool) -> str:
    """Одна формулировка выдачи ссылки на /send и /relink.

    Две копии разошлись бы: сначала в сроке, потом в предупреждении про
    название сметы — а предупреждение здесь важнее текста вокруг него.
    """
    life = FOREVER if approved else UNTIL.format(days=share.DEFAULT_TTL_DAYS)
    return LINK_BLOCK.format(url=url, life=life)


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
        approved = estimate.approved_at is not None

    await update.message.reply_text(
        SENT.format(
            number=number,
            version=version,
            total=format_money(totals.total),
            link=link_block(f"{share_base_url()}/e/{token}", approved),
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_relink(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """Заказчик потерял ссылку, а у прораба её тоже нет — вот выход.

    Подтверждение спрашивается только тогда, когда есть что закрывать: если
    живой ссылки нет, обещать «старая перестанет работать» было бы неправдой.
    """
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        if estimate.is_draft:
            await update.message.reply_text(RELINK_DRAFT)
            return

        live = share.latest_for(db, estimate.id)
        if live is not None and live.is_live:
            question = RELINK_ASK.format(
                number=estimate.number,
                version=describe_version(estimate),
                approved=RELINK_APPROVED if estimate.approved_at else "",
            )
            keyboard = confirm_keyboard("relink", estimate.id)
            await update.message.reply_text(question, reply_markup=keyboard)
            return

        token = share.reissue(db, estimate)
        message = RELINKED.format(
            number=estimate.number,
            version=estimate.version,
            link=link_block(f"{share_base_url()}/e/{token}", estimate.approved_at is not None),
        )

    await update.message.reply_text(
        message, parse_mode=ParseMode.HTML, disable_web_page_preview=True
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
            f"<b>Смета №{estimate.number}, {describe_version(estimate)}</b>\n"
            f"{esc(estimate.name)}",
            f"Открыта: {_moment(link.first_viewed_at)}",
            f"Последний раз: {_moment(link.last_viewed_at)}",
        ]
        if estimate.approved_at is not None:
            lines.append(f"✅ Согласована: {_moment(estimate.approved_at)}, бессрочно")
        if link.revoked_at is not None:
            lines.append(f"Ссылка отозвана: {_moment(link.revoked_at)}. Новая: /relink")
        elif link.expires_at is not None:
            lines.append(f"Ссылка действует до: {spell_date(link.expires_at.date())}")

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
        if estimate.approved_at is None:
            share.revoke(db, link)
            await update.message.reply_text(REVOKED)
            return
        question = REVOKE_APPROVED.format(
            number=estimate.number,
            version=estimate.version,
            on=spell_date(estimate.approved_at.date()),
        )
        keyboard = confirm_keyboard("revoke", estimate.id)

    await update.message.reply_text(question, reply_markup=keyboard)
