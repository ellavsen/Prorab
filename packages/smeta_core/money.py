"""Денежные типы, округление, границы домена и разбор чисел.

Только stdlib и Decimal. float в этом модуле запрещён (см. ADR-003).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class RateBase(StrEnum):
    """От чего берётся процент. Одна ставка, два разных основания.

    Слово «6%» само по себе неоднозначно, и неоднозначно в нём именно это:

        от цены исполнителя  250 × 1,06        = 265,00
        от суммы заказчику   250 / (1 − 0,06)  = 265,96

    Второе — не наценка прораба, а условие договора с заказчиком: процент
    удерживается ИЗ выставленной суммы, поэтому её приходится тянуть вверх,
    чтобы исполнитель получил свою цену. При умножении на 1,06 исполнитель
    недополучает с каждой строки.

    Значения английские: это код, а не экран (как Category и EstimateStatus).
    """

    COST = "cost"    # процент от цены исполнителя
    PRICE = "price"  # процент от суммы заказчику


MONEY_EXP = Decimal("0.01")
QTY_EXP = Decimal("0.001")
RATE_EXP = Decimal("0.01")

ZERO = Decimal("0.00")

# Границы домена (docs/money.md §1.2). Существуют не для красоты: они держат
# произведение qty*price в пределах 15 значащих цифр, что и даёт точный
# паритет с формулами Excel.
QTY_MAX = Decimal("99999.999")
PRICE_MAX = Decimal("9999999.99")
RATE_MAX = Decimal("99.99")

# Отдельный, куда более низкий потолок для процента от суммы заказчику. Там
# ставка делит, а не умножает, и множитель растёт неограниченно: 50% дают ×2,
# 90% — ×10, 99,99% — ×10 000, а 100% — деление на ноль. Половина удерживает
# множитель в тех же ×2, под которые посчитан бюджет 15 значащих цифр
# (money.md §3.4); выше него паритет с живой формулой Excel не проверялся.
PRICE_RATE_MAX = Decimal("50.00")

# Потолок суммы одной строки. Выше 10^9 точное значение перестаёт помещаться
# в 15 значащих цифр, и живая формула Excel начинает расходиться с Decimal
# на копейку (замерено: 0 расхождений на 385 891 строке ниже потолка,
# расхождения начиная с 10^9). Ограничение существует ради инварианта И1.
LINE_MAX = Decimal("999999999.99")

# Единственный допустимый вид числа во вводе: 12 или 12.5.
# Ни 1e3, ни NaN, ни Infinity, ни 0x10 — Decimal() их принимает, мы нет.
_NUMBER = re.compile(r"^\d+(\.\d+)?$")


def round2(x: Decimal) -> Decimal:
    """Округление до копеек, ROUND_HALF_UP: 0.005 -> 0.01."""
    return x.quantize(MONEY_EXP, rounding=ROUND_HALF_UP)


def unit_price(total: Decimal, qty: Decimal) -> Decimal:
    """Цена за единицу из суммы «за всё».

    В основном пути НЕ вызывается. Человек сказал «тридцать тысяч за всё» —
    заказчик обязан увидеть тридцать тысяч, поэтому такая строка схлопывается
    в комплект, а не делится. Обратное преобразование теряет копейки:
    30000 / 7 = 4285.71, и 7 × 4285.71 = 29999.97.

    Поэтому делить можно только по явной просьбе человека, показав ему
    потерю заранее (ADR-012).
    """
    return round2(total / qty)


def format_money(d: Decimal) -> str:
    """Единственный способ показать деньги. Арифметики здесь нет."""
    return f"{d:.2f}".replace(".", ",")


def format_qty(d: Decimal) -> str:
    """Количество без хвостовых нулей: 40.500 -> 40,5; 12.000 -> 12."""
    s = f"{d:.3f}".rstrip("0").rstrip(".")
    return (s or "0").replace(".", ",")


def _decimals(d: Decimal) -> int:
    exponent = d.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _parse_number(raw: str, field: str) -> Decimal:
    s = str(raw).strip().replace(" ", " ").replace(" ", "").replace(",", ".")
    if not s:
        raise ValueError(f"{field}: значение не указано")
    if s.startswith("-"):
        raise ValueError(f"{field}: отрицательные значения не допускаются")
    if not _NUMBER.match(s):
        raise ValueError(f"{field}: «{raw}» — это не число. Ожидается 12 или 12,5")
    return Decimal(s)


def check_price(value: Decimal, field: str = "Цена") -> Decimal:
    if _decimals(value) > 2:
        raise ValueError(f"{field}: не более 2 знаков после запятой")
    if value < 0:
        raise ValueError(f"{field}: отрицательные значения не допускаются")
    if value > PRICE_MAX:
        raise ValueError(f"{field}: не больше {format_money(PRICE_MAX)}")
    return value


def check_quantity(value: Decimal, field: str = "Количество") -> Decimal:
    if _decimals(value) > 3:
        raise ValueError(
            f"{field}: не более 3 знаков после запятой. "
            f"Округли сам — 12,3456 это 12,346 или 12,35?"
        )
    if value <= 0:
        raise ValueError(f"{field}: должно быть больше нуля")
    if value > QTY_MAX:
        raise ValueError(f"{field}: не больше {format_qty(QTY_MAX)}")
    return value


def rate_ceiling(base: RateBase = RateBase.COST) -> Decimal:
    return PRICE_RATE_MAX if RateBase(base) is RateBase.PRICE else RATE_MAX


def check_rate(
    value: Decimal, field: str = "Наценка", base: RateBase = RateBase.COST
) -> Decimal:
    ceiling = rate_ceiling(base)
    if _decimals(value) > 2:
        raise ValueError(f"{field}: не более 2 знаков после запятой")
    if value < 0 or value > ceiling:
        raise ValueError(f"{field}: должна быть в пределах 0…{format_money(ceiling)}%")
    return value


def parse_price(raw: str, field: str = "Цена") -> Decimal:
    return check_price(_parse_number(raw, field), field).quantize(MONEY_EXP)


def parse_quantity(raw: str, field: str = "Количество") -> Decimal:
    return check_quantity(_parse_number(raw, field), field).quantize(QTY_EXP)


def parse_rate(
    raw: str, field: str = "Наценка", base: RateBase = RateBase.COST
) -> Decimal:
    return check_rate(_parse_number(raw, field), field, base).quantize(RATE_EXP)


# --- Граница хранилища: Decimal <-> целые минорные единицы (ADR-004) ---
# Вызывать только в репозитории. В домене этих чисел не существует.

def to_kop(value: Decimal) -> int:
    return int(check_price(value).quantize(MONEY_EXP).scaleb(2))


def from_kop(value: int) -> Decimal:
    return Decimal(value).scaleb(-2).quantize(MONEY_EXP)


def to_milli(value: Decimal) -> int:
    return int(check_quantity(value).quantize(QTY_EXP).scaleb(3))


def from_milli(value: int) -> Decimal:
    return Decimal(value).scaleb(-3).quantize(QTY_EXP)


def to_bp(value: Decimal) -> int:
    return int(check_rate(value).quantize(RATE_EXP).scaleb(2))


def from_bp(value: int) -> Decimal:
    return Decimal(value).scaleb(-2).quantize(RATE_EXP)
