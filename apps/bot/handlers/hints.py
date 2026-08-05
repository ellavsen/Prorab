"""Подсказка цены по своей истории.

Предложение, а не подстановка. Строка без цены остаётся негодной и в сумму не
входит, пока человек не нажал кнопку: между моделью и сметой стоит он, и между
историей и сметой — тоже (ADR-012, ADR-017).

Молчание здесь — решение, а не пробел. Своих цен нет — подсказки нет; «нет
данных» на пустом месте только шумит, а строка и так видна с причиной.
"""

from __future__ import annotations

from dataclasses import replace

from smeta_prices import from_history, normalize_name
from smeta_storage import PendingRow, history, pending


def _hinted(db, uid: int, row: PendingRow) -> PendingRow:
    """Строку без цены дополняем тем, что человек платил сам.

    Подсказываем только там, где не хватает ровно цены. Если нет ещё и
    количества, цена строку не спасёт — она так и останется непосчитанной,
    а кнопка обещала бы обратное.
    """
    if row.price or not row.qty:
        return row

    points = history.lookup(db, uid, row.name, row.unit, row.unit_spoken,
                            category=row.category)
    hint = from_history(points, performer=row.performer or "")
    if hint is None:
        return row

    return replace(
        row,
        # Пусто, когда последняя цена не определена. Кнопка «Последняя»
        # берётся отсюда же, поэтому вместе с числом гаснет и она (ADR-026).
        hint_price=None if hint.last is None else str(hint.last),
        hint_median=None if hint.median is None else str(hint.median),
        hint_low=str(hint.low),
        hint_high=str(hint.high),
        # Молчим о совпадении и говорим о несовпадении: цена, найденная под
        # другим наименованием, обязана назвать его (ADR-027).
        hint_matched_name=(
            hint.matched if hint.matched != normalize_name(row.name) else None
        ),
        hint_on=hint.on,
        hint_times=hint.times,
    )


def attach(db, uid: int, rows: list[PendingRow]) -> list[PendingRow]:
    return [_hinted(db, uid, row) for row in rows]


def apply(db, uid: int, ordinal: int, median: bool = False) -> bool:
    """Человек нажал «взять». Цена появляется в строке — и только теперь.

    Причина, по которой строка не считалась, снимается вместе с этим: цена
    названа, а больше строке ничего не мешало — иначе подсказки бы не было.
    """
    row = pending.get(db, uid, ordinal)
    if row is None:
        return False

    price = row.hint_median if median else row.hint_price
    if not price:
        return False

    row.price = price
    row.price_scope = "per_unit"
    row.problem = None
    db.commit()
    return True


def hinted_ordinals(rows, median: bool = False) -> list[int]:
    """Строки, у которых есть что предложить. Пусто — кнопок не будет."""
    return [
        row.ordinal for row in rows
        if (row.hint_median if median else row.hint_price)
    ]
