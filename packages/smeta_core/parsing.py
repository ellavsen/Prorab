"""Разбор пользовательского ввода в позицию сметы.

Формат строки: «Наименование, количество, цена».
Количество может нести единицу измерения: «150 м2».

Запятая в этой строке работает сразу в трёх ролях: разделитель полей,
десятичный разделитель и обычный символ внутри наименования («Гвозди 3,5 мм»).
Поэтому разбор идёт справа: последние два поля — количество и цена, всё
остальное слева — наименование, каким его напечатали.

Если строку можно прочитать двумя способами и суммы при этом расходятся,
парсер не выбирает молча, а сообщает об этом (ADR-011).
"""

from __future__ import annotations

import re

from .models import Category, PositionData, check_name
from .money import parse_price, parse_quantity
from .units import normalize_unit

# Число, затем необязательный хвост-единица: «150 м2», «1.5», «2 шт».
_QTY_WITH_UNIT = re.compile(r"^(?P<num>[\d\s.,]*\d)\s*(?P<unit>.*)$")

# Запятая строго между цифрами и без пробелов — десятичный разделитель.
# «150,5» подходит, «100, 20» нет.
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")

_FORMAT_HINT = (
    "Нужно три поля через запятую: Наименование, количество, цена.\n"
    "Пример: <code>Побелка, 150 м2, 3000</code>"
)


class AmbiguousLine(ValueError):
    """Строку можно прочитать двумя способами, и суммы получаются разные."""

    def __init__(self, line: str, plain: PositionData, merged: PositionData) -> None:
        self.line = line
        self.plain = plain      # запятая — разделитель полей
        self.merged = merged    # запятая — десятичный разделитель
        super().__init__(
            f"«{line}» читается двумя способами: "
            f"количество {plain.qty} или {merged.qty}. Уточни."
        )


def split_qty_unit(raw: str) -> tuple[str, str]:
    """«150 м2» -> ("150", "м²"). Неизвестная единица отбрасывается."""
    match = _QTY_WITH_UNIT.match(raw.strip())
    if not match:
        return raw.strip(), ""
    return match.group("num"), normalize_unit(match.group("unit"))


def _read(line: str, category: Category) -> PositionData:
    """Одно прочтение строки. Наименование берётся как напечатано."""
    parts = [part.strip() for part in line.rsplit(",", 2)]
    if len(parts) < 3:
        raise ValueError(f"получено полей: {line.count(',') + 1}, а нужно 3.\n{_FORMAT_HINT}")

    name, qty_raw, price_raw = parts
    qty_text, unit = split_qty_unit(qty_raw)
    return PositionData(
        category=category,
        name=check_name(name),
        qty=parse_quantity(qty_text),
        price=parse_price(price_raw),
        unit=unit,
    )


def _try_read(line: str, category: Category) -> tuple[PositionData | None, ValueError | None]:
    try:
        return _read(line, category), None
    except ValueError as error:
        return None, error


def parse_position_line(line: str, category: Category) -> PositionData:
    """Разбирает строку ввода.

    Обычная проблема — ValueError с текстом для пользователя.
    Неоднозначность — AmbiguousLine с обоими прочтениями.
    """
    raw = (line or "").strip()
    merged = _DECIMAL_COMMA.sub(".", raw)

    plain_result, plain_error = _try_read(raw, category)
    if merged == raw:
        if plain_result is None:
            raise plain_error
        return plain_result

    merged_result, merged_error = _try_read(merged, category)
    if plain_result is None and merged_result is None:
        raise plain_error or merged_error
    if plain_result is None:
        return merged_result
    if merged_result is None:
        return plain_result

    # Оба прочтения допустимы. Если деньги совпадают, различие только в тексте
    # наименования — тогда берём тот, что напечатал человек, и не переспрашиваем.
    if (plain_result.qty, plain_result.price) == (merged_result.qty, merged_result.price):
        return plain_result
    raise AmbiguousLine(raw, plain_result, merged_result)
