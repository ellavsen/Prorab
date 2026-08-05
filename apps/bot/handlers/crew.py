"""Команда /who: кто делает работу.

Три формы, и ни одна не заводит настроечного экрана:

    /who Саня          — всем строкам сметы, у которых исполнителя ещё нет,
                         и дальше по умолчанию новым пачкам
    /who Саня #41 #43  — ровно этим строкам, той же адресацией, что /delete
    /who off           — снять липкость

Диапазона «3-7» здесь нет намеренно: в /list показываются идентификаторы
строк, сквозные по всей базе, а не номера 1..N. Диапазон по ним выглядел бы
осмысленно и промахивался (ADR-028).
"""

import re
from dataclasses import replace

from telegram import Update
from telegram.ext import ContextTypes

from smeta_prices import CATALOG
from smeta_storage import current_estimate, performers, touch_estimate

from ..database import SessionLocal
from ..texts import esc

USAGE = (
    "Кто делает работу:\n"
    "<code>/who Саня</code> — всем строкам без исполнителя, и дальше новым\n"
    "<code>/who Саня #41 #43</code> — только этим строкам\n"
    "<code>/who off</code> — больше никого не проставлять"
)

_ID = re.compile(r"#?(\d+)")


def parse(tail: str) -> tuple[str, list[int] | None]:
    """Хвост команды -> (имя, строки). Пусто в строках — значит «всем без имени».

    Имя может состоять из нескольких слов: «Саня Паша» — это несколько
    исполнителей на одной строке, и мы храним их как названо. Делить сумму
    между ними бот не будет: «по 1200» на троих значит 1200 каждому, а не
    треть от 1200 (ADR-028).
    """
    words = tail.split()
    ids = [int(_ID.fullmatch(word).group(1)) for word in words if _ID.fullmatch(word)]
    name = " ".join(word for word in words if not _ID.fullmatch(word)).strip()
    return name, (ids or None)


def apply_sticky(db, uid: int, rows: list) -> tuple[list, list[str]]:
    """Проставляет липкого исполнителя распознанной пачке.

    Уже названного не перебивает, аренду пропускает и называет её вслух:
    у бетономешалки исполнителя не бывает, а тихий пропуск выглядит сбоем
    (ADR-029).
    """
    who = performers.sticky(db, uid)
    if not who:
        return rows, []

    stuck, rented = [], []
    for row in rows:
        if row.performer or CATALOG.takes_performer(row.name):
            stuck.append(row if row.performer else replace(row, performer=who))
        else:
            stuck.append(row)
            rented.append(row.name)
    performers.touch(db, uid)
    return stuck, rented


async def cmd_who(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    tail = (update.message.text or "").partition(" ")[2].strip()
    if not tail:
        await update.message.reply_text(USAGE, parse_mode="HTML")
        return

    uid = update.effective_user.id
    if tail.lower() in {"off", "выкл", "никто"}:
        with SessionLocal() as db:
            performers.forget_sticky(db, uid)
        await update.message.reply_text(
            "Больше никого не проставляю. Уже записанное осталось как есть."
        )
        return

    name, ids = parse(tail)
    if not name:
        await update.message.reply_text(USAGE, parse_mode="HTML")
        return

    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        touched, skipped = performers.assign(db, uid, estimate.id, name, ids)
        if ids is None:
            # Липким делает только форма без списка: назвав строки поимённо,
            # человек говорил про них, а не про всё, что будет дальше.
            performers.remember(db, uid, name)
        if touched:
            touch_estimate(db, estimate)

    who = esc(name)
    lines = [f"Проставила {who}: строк — {touched}."]
    if skipped:
        # Аренда — не работа человека. Пропуск назван, иначе он выглядит сбоем.
        lines.append(
            "Пропустила аренду, исполнителя там не бывает: "
            + ", ".join(esc(one) for one in dict.fromkeys(skipped))
        )
    if ids is None:
        lines.append("Дальше новые строки тоже будут его. Отменить: /who off")
    await update.message.reply_text("\n".join(lines))
