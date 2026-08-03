"""Единственный источник истины по суммам сметы (ADR-002).

Никакой другой код в проекте не умножает деньги. /list, /estimates, XLSX и
любой будущий канал — потребители результата этой функции.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal

from .models import Category, EstimateTotals, LineTotal, PositionData
from .money import LINE_MAX, ZERO, RateBase, check_rate, format_money, round2

_HUNDRED = Decimal("100")
_ONE = Decimal("1")


def _gross(base: Decimal, rate: Decimal, rate_base: RateBase) -> Decimal:
    """Единственное место, где ставка превращается в деньги.

        от цены исполнителя: base × (1 + r/100)      250 → 265,00
        от суммы заказчику:  base / (1 − r/100)      250 → 265,96

    Второй случай именно ДЕЛИТ, а не умножает на обратное. В ячейке XLSX
    стоит `=ROUND(F{r}/(1-$B$1/100),2)`, и Python обязан повторять формулу
    буквально: 1/0,94 в Decimal — это 28 знаков, и совпадение умножения с
    делением было бы везением, а не свойством, на которое можно опереться.
    """
    if RateBase(rate_base) is RateBase.PRICE:
        return round2(base / (_ONE - rate / _HUNDRED))
    return round2(base * (_ONE + rate / _HUNDRED))


def calculate_estimate(
    positions: Sequence[PositionData],
    markup_work_rate: Decimal,
    markup_material_rate: Decimal,
    rate_base: RateBase = RateBase.COST,
) -> EstimateTotals:
    """Считает смету по схеме docs/money.md §2.

    Ставки — проценты: 6.00 означает 6%. Основание общее на всю смету
    (условие договора с заказчиком), ставки раздельные по категориям:
    договор вполне может удерживать процент с работ и не трогать материалы.

        base   = round2(qty * price)
        line   = round2(наценка по основанию)
        subtotal = Σ base, total = Σ line, markup = total − subtotal

    Итог — сумма УЖЕ округлённых строк, поэтому «сумма строк на экране»
    равна «Итого» по построению, а не по совпадению.
    """
    check_rate(markup_work_rate, "Наценка на работы", rate_base)
    check_rate(markup_material_rate, "Наценка на материалы", rate_base)

    rate = {
        Category.WORK: markup_work_rate,
        Category.MATERIAL: markup_material_rate,
    }

    lines: list[LineTotal] = []
    for position in positions:
        base = round2(position.qty * position.price)
        line_total = _gross(base, rate[Category(position.category)], rate_base)
        if line_total > LINE_MAX:
            raise ValueError(
                f"«{position.name}»: сумма строки {format_money(line_total)} "
                f"превышает потолок {format_money(LINE_MAX)}. Выше него живая "
                f"формула Excel расходится с расчётом на копейку — разбей позицию."
            )
        lines.append(LineTotal(position=position, base=base, total=line_total))

    subtotal = sum_lines(lines, base=True)
    total = sum_lines(lines)

    return EstimateTotals(
        lines=tuple(lines),
        subtotal=subtotal,
        markup=total - subtotal,
        total=total,
    )


def sum_lines(lines: Iterable[LineTotal], base: bool = False) -> Decimal:
    """Сумма уже округлённых строк. Единственный способ сложить деньги.

    Нужна не только внутри: документ печатает ещё и промежуточные итоги по
    разделам («итого работы»), и складывать их своим циклом в каждом
    генераторе значило бы завести второе правило суммирования. Оно бы
    разошлось — ровно так же, как расходились четыре вычислителя до Sprint 1.
    """
    return sum((line.base if base else line.total for line in lines), ZERO)
