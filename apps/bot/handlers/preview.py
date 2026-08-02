"""Предпросмотр распознанной пачки: показать, дать поправить, добавить.

Между моделью и сметой всегда стоит человек. Ни одна строка отсюда не попадает
в смету без нажатия (ADR-012).

Хендлеры принимают message/query и db, а не Update, — как в stepwise.py:
так их можно проверить заглушками, без Telegram и без сети.
"""

from __future__ import annotations

from dataclasses import replace

from telegram import Message
from telegram.constants import ParseMode

from smeta_ai import (
    FieldStatus,
    PositionCandidate,
    Price,
    PriceScope,
    Quantity,
    check_candidate,
    collapse_total_scope,
    pick_category,
    to_position,
)
from smeta_core import (
    Category,
    PositionData,
    calculate_estimate,
    default_unit,
)
from smeta_storage import (
    PendingRow,
    current_estimate,
    pending,
    positions,
    touch_estimate,
    user_state,
)

from ..keyboards import pending_keyboard
from ..texts import (
    AI_NOTHING,
    PREVIEW_CANCELLED,
    esc,
    render_pending,
    render_units_substituted,
)
from . import split


def _check(position, estimate) -> str | None:
    """None — позиция считается; иначе причина, по которой нет.

    Считает домен, а не хендлер: границы суммы строки живут в calculate_estimate.
    """
    try:
        calculate_estimate(
            [position], estimate.markup_work_rate, estimate.markup_material_rate
        )
    except ValueError as error:
        return str(error)
    return None


def build_rows(extraction, estimate, fallback: Category, source: str | None):
    """Кандидаты -> строки предпросмотра и журнал подставленных единиц.

    Негодная строка не выбрасывается: она попадает в предпросмотр с причиной.
    Молча терять то, что человек продиктовал, нельзя.
    """
    rows: list[PendingRow] = []
    substituted: dict[str, list[str]] = {}

    for original in extraction.positions:
        candidate = collapse_total_scope(original)
        totals = _total_fields(original, candidate)

        problem = check_candidate(candidate, source, fallback)
        if problem is not None:
            rows.append(PendingRow(
                category=pick_category(candidate.category, fallback).value,
                name=candidate.name or "(без наименования)",
                qty=candidate.qty.value, price=candidate.price.value,
                unit=candidate.unit, unit_spoken=candidate.unit_spoken,
                price_scope=original.price.scope,
                problem=problem, **totals,
            ))
            continue

        position = to_position(candidate, fallback)
        if not position.unit:
            unit = default_unit(position.category)
            position = replace(position, unit=unit)
            substituted.setdefault(unit, []).append(position.name)

        rows.append(PendingRow(
            category=position.category.value,
            name=position.name,
            qty=str(position.qty),
            price=str(position.price),
            unit=position.unit,
            unit_spoken=position.unit_spoken,
            price_scope=original.price.scope,
            problem=_check(position, estimate),
            **totals,
        ))
    return rows, substituted


def _total_fields(original, collapsed) -> dict:
    """Что было сказано до схлопывания — по этому работает кнопка «÷».

    Заполняется в двух случаях: строку схлопнули из «за всё», либо модель не
    поняла, за единицу цена или за всё. Во втором считаем как за единицу —
    третьей ветки расчёта нет, — но кнопку оставляем под рукой (ADR-012).
    """
    unclear = (
        collapsed is original
        and original.price.scope == PriceScope.UNKNOWN
        and original.price.value
        and original.qty.value
    )
    if collapsed is not original or unclear:
        return {
            "total_price": original.price.value,
            "total_qty": original.qty.value,
            "total_unit": original.unit_spoken or original.unit,
        }
    return {}


def _position_of(row) -> PositionData:
    """Строка предпросмотра обратно в позицию. Значения уже нормализованы."""
    return to_position(
        PositionCandidate(
            name=row.name,
            qty=Quantity(status=FieldStatus.STATED, value=row.qty),
            price=Price(status=FieldStatus.STATED, scope=PriceScope.PER_UNIT,
                        value=row.price),
            unit=row.unit,
            unit_spoken=row.unit_spoken,
            category=row.category,
        ),
        Category(row.category),
    )


def computed(rows, estimate):
    """Суммы строк предпросмотра. Единственный источник — calculate_estimate."""
    good = [row for row in rows if not row.problem]
    totals = calculate_estimate(
        [_position_of(row) for row in good],
        estimate.markup_work_rate,
        estimate.markup_material_rate,
    )
    by_ordinal = dict(zip([row.ordinal for row in good], totals.lines, strict=True))
    return by_ordinal, totals


async def show_preview(target, db, uid: int, edit: bool = False) -> None:
    rows = pending.load(db, uid)
    estimate = current_estimate(db, uid)
    by_ordinal, totals = computed(rows, estimate)

    text = render_pending(estimate, rows, by_ordinal, totals)
    keyboard = pending_keyboard(
        [row.ordinal for row in rows],
        addable=len(by_ordinal),
        splittable=[row.ordinal for row in rows if row.total_price],
    )
    if edit:
        await target.edit_message_text(text, parse_mode=ParseMode.HTML,
                                       reply_markup=keyboard)
    else:
        await target.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def offer(message: Message, db, uid: int, extraction, source: str | None = None) -> None:
    """Кладёт распознанное в предпросмотр. В смету не пишет ничего."""
    estimate = current_estimate(db, uid)
    fallback = Category(user_state(db, uid).category or Category.MATERIAL)
    rows, substituted = build_rows(extraction, estimate, fallback, source)

    if not rows:
        await message.reply_text(AI_NOTHING)
        return

    pending.replace(db, uid, estimate.id, rows)
    for unit, names in substituted.items():
        await message.reply_text(render_units_substituted(names, unit))
    await show_preview(message, db, uid)


async def handle_action(query, db, uid: int, action: str) -> None:
    verb, _, value = action.partition(":")

    if verb == "cancel":
        pending.clear(db, uid)
        await query.edit_message_text(PREVIEW_CANCELLED)
        return

    if verb == "drop":
        pending.drop(db, uid, int(value))
        if not pending.load(db, uid):
            await query.edit_message_text(PREVIEW_CANCELLED)
            return
        await show_preview(query, db, uid, edit=True)
        return

    if verb == "split":
        if not await split.offer(query, db, uid, int(value)):
            await show_preview(query, db, uid, edit=True)
        return

    if verb == "dosplit":
        split.apply(db, uid, int(value))
        await show_preview(query, db, uid, edit=True)
        return

    if verb == "back":
        await show_preview(query, db, uid, edit=True)
        return

    await _add_all(query, db, uid)


async def _add_all(query, db, uid: int) -> None:
    rows = pending.load(db, uid)
    estimate = current_estimate(db, uid)
    by_ordinal, _ = computed(rows, estimate)

    added, refused = 0, []
    for row in rows:
        line = by_ordinal.get(row.ordinal)
        if line is None:
            continue
        try:
            positions.add(db, uid, estimate.id, line.position)
        except ValueError as error:
            refused.append(f"{esc(row.name)} — {esc(error)}")
            continue
        added += 1

    touch_estimate(db, estimate)
    skipped = len(rows) - added
    pending.clear(db, uid)

    report = [f"Добавлено позиций: <b>{added}</b>. Посмотреть: /list"]
    if skipped:
        report.append(f"Не добавлено: {skipped} — их не удалось разобрать.")
    report.extend(refused)
    await query.edit_message_text("\n".join(report), parse_mode=ParseMode.HTML)
