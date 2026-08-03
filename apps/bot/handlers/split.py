"""Разбиение строки, названной «за всё», на позиции.

В основном пути деления нет: человек сказал тридцать тысяч — заказчик обязан
увидеть тридцать тысяч. Но если он сам просит разделить, показать потерю копеек
надо ДО того, как она случится (ADR-012).

Сюда же попадают строки, где модель не поняла, за единицу цена или за всё:
считаются они за единицу, а кнопка остаётся под рукой.
"""

from __future__ import annotations

from telegram.constants import ParseMode

from smeta_ai import FieldStatus, PositionCandidate, Quantity, counted_name
from smeta_core import (
    ZERO,
    Category,
    PositionData,
    calculate_estimate,
    parse_price,
    parse_quantity,
    unit_decision,
    unit_price,
)
from smeta_storage import pending

from ..keyboards import split_keyboard
from ..preview_texts import (
    render_split,
)


def split_math(row):
    """Что получится при делении. Умножения тут нет — считает домен."""
    total, count = parse_price(row.total_price), parse_quantity(row.total_qty)
    each = unit_price(total, count)
    probe = PositionData(
        category=Category(row.category), name=row.name, qty=count, price=each
    )
    restored = calculate_estimate([probe], ZERO, ZERO).subtotal
    return each, count, restored, total - restored


def original_name(row) -> str:
    """Убирает суффикс, который приписало схлопывание, — ровно тот же.

    Строка, которую не схлопывали, суффикса не имеет, и removesuffix
    ничего не делает.
    """
    probe = PositionCandidate(
        name="", qty=Quantity(status=FieldStatus.STATED, value=row.total_qty or ""),
        unit_spoken=row.total_unit or "",
    )
    return row.name.removesuffix(counted_name(probe))


async def offer(query, db, uid: int, ordinal: int) -> bool:
    """Показывает дельту. False — делить нечего, зовущий вернёт предпросмотр."""
    row = pending.get(db, uid, ordinal)
    if row is None or not row.total_price:
        return False

    each, count, restored, delta = split_math(row)
    await query.edit_message_text(
        render_split(original_name(row), count, each, restored, delta,
                     parse_price(row.total_price), row.total_unit or ""),
        parse_mode=ParseMode.HTML,
        reply_markup=split_keyboard(ordinal),
    )
    return True


def apply(db, uid: int, ordinal: int) -> None:
    row = pending.get(db, uid, ordinal)
    if row is None or not row.total_price:
        return

    each, count, _restored, _delta = split_math(row)
    row.name = original_name(row)
    row.qty = str(count)
    row.price = str(each)
    row.unit_spoken = row.total_unit or ""
    row.unit = unit_decision("", row.unit_spoken)
    row.price_scope = "per_unit"        # вопрос закрыт человеком
    row.total_price = row.total_qty = row.total_unit = None
    db.commit()
