"""Мост между браузером и ядром.

Исполняется внутри Pyodide. Здесь нет ни одного арифметического действия:
всё считает smeta_core — тот же самый, что в боте и в API. Обмен идёт
JSON-строками, чтобы не зависеть от преобразования объектов JS <-> Python.

Деньги отдаются двумя полями: канонической строкой ("159.16") и готовым
к показу текстом ("159,16"). Форматирует Python — фронт ничего не считает
и не переводит.
"""

import base64
import json
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from smeta_core import (
    UNITS,
    AmbiguousLine,
    Category,
    PositionData,
    calculate_estimate,
    default_unit,
    format_money,
    format_qty,
    parse_position_line,
)
from smeta_export import build_workbook


def _money(value: Decimal) -> dict:
    return {"value": str(value), "text": format_money(value)}


def _position_to_json(position: PositionData) -> dict:
    return {
        "category": str(position.category),
        "name": position.name,
        "unit": position.unit,
        "qty": str(position.qty),
        "qty_text": format_qty(position.qty),
        "price": str(position.price),
        "price_text": format_money(position.price),
    }


def _position_from_json(raw: dict, fill_units: bool = True) -> PositionData:
    category = Category(raw["category"])
    position = PositionData(
        category=category,
        name=raw["name"],
        qty=Decimal(str(raw["qty"])),
        price=Decimal(str(raw["price"])),
        unit=raw.get("unit") or "",
    )
    if not position.unit and fill_units:
        position = replace(position, unit=default_unit(category))
    return position


def units() -> str:
    return json.dumps(list(UNITS))


def parse_lines(payload: str) -> str:
    """Разбирает текст в позиции. Плохая строка не роняет остальные."""
    request = json.loads(payload)
    category = Category(request["category"])
    fill_units = request.get("fill_units", True)

    positions, errors = [], []
    for line in (raw.strip() for raw in request["text"].splitlines()):
        if not line:
            continue
        try:
            position = parse_position_line(line, category)
        except AmbiguousLine as error:
            # Оба прочтения показываем целиком: выбор за человеком (ADR-011).
            errors.append({
                "line": line,
                "reason": str(error),
                "readings": [
                    _position_to_json(error.plain),
                    _position_to_json(error.merged),
                ],
            })
            continue
        except (ValueError, InvalidOperation) as error:
            errors.append({"line": line, "reason": str(error), "readings": []})
            continue
        if not position.unit and fill_units:
            position = replace(position, unit=default_unit(category))
        positions.append(_position_to_json(position))
    return json.dumps({"positions": positions, "errors": errors})


def calculate(payload: str) -> str:
    """Итоги сметы. Единственный вычислитель — calculate_estimate."""
    request = json.loads(payload)
    try:
        positions = [_position_from_json(raw) for raw in request["positions"]]
        totals = calculate_estimate(
            positions,
            Decimal(str(request["markup_work_rate"])),
            Decimal(str(request["markup_material_rate"])),
            request.get("rate_base", "cost"),
        )
    except (ValueError, InvalidOperation) as error:
        return json.dumps({"error": str(error)})

    return json.dumps({
        "lines": [
            {
                **_position_to_json(line.position),
                "base": _money(line.base),
                "total": _money(line.total),
            }
            for line in totals.lines
        ],
        "subtotal": _money(totals.subtotal),
        "markup": _money(totals.markup),
        "total": _money(totals.total),
    })


def xlsx_base64(payload: str) -> str:
    """XLSX с живыми формулами — тот же build_workbook, что отдаёт бот."""
    request = json.loads(payload)
    try:
        positions = [_position_from_json(raw) for raw in request["positions"]]
        work_rate = Decimal(str(request["markup_work_rate"]))
        material_rate = Decimal(str(request["markup_material_rate"]))
        base = request.get("rate_base", "cost")
        # Расчёт отвергнет смету, где строка выше потолка, до выдачи файла.
        calculate_estimate(positions, work_rate, material_rate, base)
    except (ValueError, InvalidOperation) as error:
        return json.dumps({"error": str(error)})

    buffer = build_workbook(
        [p for p in positions if p.category == Category.MATERIAL],
        [p for p in positions if p.category == Category.WORK],
        work_rate,
        material_rate,
        base,
    )
    return json.dumps({"base64": base64.b64encode(buffer.getvalue()).decode("ascii")})
