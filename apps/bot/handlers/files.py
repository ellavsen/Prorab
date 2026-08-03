"""Хендлер /generate: XLSX по текущей смете."""

from datetime import datetime

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from smeta_core import format_money
from smeta_export import build_workbook, document_filename
from smeta_storage import current_estimate, positions

from ..database import SessionLocal
from ..texts import markup_caption


async def cmd_generate(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        materials, works = positions.by_category(db, uid, estimate.id)
        if not materials and not works:
            await update.message.reply_text(
                "Нет данных для отчёта в текущей смете. Добавь позиции и повтори /generate."
            )
            return

        totals = positions.totals(db, uid, estimate)
        buffer = build_workbook(
            materials, works, estimate.markup_work_rate, estimate.markup_material_rate
        )

    # Имя уходит заказчику вместе с файлом, поэтому строит его функция, в
    # которую нечего передать лишнего: раньше здесь стоял user_id (ADR-001).
    filename = document_filename(
        estimate.number, "xlsx", on=datetime.now().astimezone().date()
    )
    await update.message.reply_document(
        document=InputFile(buffer, filename=filename),
        caption=(
            f"Готово: {estimate.name} (№{estimate.number}). "
            f"Две вкладки: «Работы» и «Материалы».\n"
            f"Наценка {markup_caption(estimate)}, итог {format_money(totals.total)} — "
            f"столько же, сколько в /list."
        ),
    )
