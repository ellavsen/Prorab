"""Единственный источник истины по суммам сметы (ADR-002).

Никакой другой код в проекте не умножает деньги. /list, /estimates, XLSX и
любой будущий канал — потребители результата этой функции.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from .models import Category, EstimateTotals, LineTotal, PositionData
from .money import LINE_MAX, ZERO, check_rate, format_money, round2

_HUNDRED = Decimal("100")
_ONE = Decimal("1")


def calculate_estimate(
    positions: Sequence[PositionData],
    markup_work_rate: Decimal,
    markup_material_rate: Decimal,
) -> EstimateTotals:
    """Считает смету по схеме docs/money.md §2.

    Ставки — проценты: 6.00 означает 6%.

        factor = 1 + rate/100
        base   = round2(qty * price)
        line   = round2(base * factor)
        subtotal = Σ base, total = Σ line, markup = total − subtotal

    Итог — сумма УЖЕ округлённых строк, поэтому «сумма строк на экране»
    равна «Итого» по построению, а не по совпадению.
    """
    check_rate(markup_work_rate, "Наценка на работы")
    check_rate(markup_material_rate, "Наценка на материалы")

    factor = {
        Category.WORK: _ONE + markup_work_rate / _HUNDRED,
        Category.MATERIAL: _ONE + markup_material_rate / _HUNDRED,
    }

    lines: list[LineTotal] = []
    for position in positions:
        base = round2(position.qty * position.price)
        line_total = round2(base * factor[Category(position.category)])
        if line_total > LINE_MAX:
            raise ValueError(
                f"«{position.name}»: сумма строки {format_money(line_total)} "
                f"превышает потолок {format_money(LINE_MAX)}. Выше него живая "
                f"формула Excel расходится с расчётом на копейку — разбей позицию."
            )
        lines.append(LineTotal(position=position, base=base, total=line_total))

    subtotal = sum((line.base for line in lines), ZERO)
    total = sum((line.total for line in lines), ZERO)

    return EstimateTotals(
        lines=tuple(lines),
        subtotal=subtotal,
        markup=total - subtotal,
        total=total,
    )
