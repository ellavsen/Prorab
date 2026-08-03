"""Хендлеры /generate и /pdf: документы по текущей смете.

Оба берут суммы у домена через verified_totals: у отправленной сметы это
означает сверку со слепком, и документ не выдаётся вовсе, если данные
разошлись с тем, что заказчик уже видел (money.md И3).
"""

from datetime import datetime

from telegram import InputFile, Update
from telegram.ext import ContextTypes

from smeta_core import IntegrityError, format_money
from smeta_export import DocumentMeta, build_pdf, build_workbook, document_filename
from smeta_storage import current_estimate, positions, verified_totals

from ..database import SessionLocal
from ..texts import STATUS_LABEL, markup_caption

EMPTY = "Нет данных для отчёта в текущей смете. Добавь позиции и повтори {command}."
BROKEN = (
    "Документ не выдан: данные сметы разошлись с тем, что было заморожено при "
    "отправке.\n{reason}"
)


def _meta(estimate, on) -> DocumentMeta:
    return DocumentMeta(
        number=estimate.number,
        version=estimate.version,
        title=estimate.name,
        on=on,
        work_rate=estimate.markup_work_rate,
        material_rate=estimate.markup_material_rate,
        status=STATUS_LABEL.get(estimate.status, ""),
    )


async def cmd_generate(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        materials, works = positions.by_category(db, uid, estimate.id)
        if not materials and not works:
            await update.message.reply_text(EMPTY.format(command="/generate"))
            return

        try:
            totals = verified_totals(db, estimate)
        except IntegrityError as error:
            await update.message.reply_text(BROKEN.format(reason=error))
            return

        buffer = build_workbook(
            materials, works, estimate.markup_work_rate, estimate.markup_material_rate
        )
        number, name, version = estimate.number, estimate.name, estimate.version

    # Имя уходит заказчику вместе с файлом, поэтому строит его функция, в
    # которую нечего передать лишнего: раньше здесь стоял user_id (ADR-001).
    filename = document_filename(
        number, "xlsx", on=datetime.now().astimezone().date(), version=version
    )
    await update.message.reply_document(
        document=InputFile(buffer, filename=filename),
        caption=(
            f"Готово: {name} (№{number}, ред. {version}). "
            f"Две вкладки: «Работы» и «Материалы».\n"
            f"Итог {format_money(totals.total)} — столько же, сколько в /list."
        ),
    )


async def cmd_pdf(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    """PDF: то же самое, но одним листом и готовыми числами."""
    uid = update.effective_user.id
    on = datetime.now().astimezone().date()
    with SessionLocal() as db:
        estimate = current_estimate(db, uid)
        if not positions.load(db, uid, estimate.id):
            await update.message.reply_text(EMPTY.format(command="/pdf"))
            return

        try:
            totals = verified_totals(db, estimate)
        except IntegrityError as error:
            await update.message.reply_text(BROKEN.format(reason=error))
            return

        buffer = build_pdf(totals, _meta(estimate, on))
        number, name, version = estimate.number, estimate.name, estimate.version

    await update.message.reply_document(
        document=InputFile(buffer, filename=document_filename(
            number, "pdf", on=on, version=version
        )),
        caption=(
            f"{name} (№{number}, ред. {version}). "
            f"Итог {format_money(totals.total)}, наценка {markup_caption(estimate)}."
        ),
    )
