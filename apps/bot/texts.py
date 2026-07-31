"""Текст сообщений. Арифметики здесь нет: суммы приходят из calculate_estimate."""

import html
from decimal import Decimal

from smeta_core import EstimateTotals, format_money, format_qty
from smeta_storage import Estimate, Position

START_TEXT = (
    "Привет! Я бот для расчёта смет.\n\n"
    "📌 Как пользоваться:\n"
    "— Нажми <b>«Начнём»</b> и выбери категорию\n"
    "— Дальше по шагам: наименование → количество → единица → цена\n"
    "— Или списком, если так быстрее: <code>Побелка, 150 м2, 3000</code>\n\n"
    "Сметы:\n"
    "/new [название] — новая смета и переключение на неё\n"
    "/estimates — список последних 5 смет\n"
    "/switch N — переключиться на смету №N\n"
    "/rate 6 — наценка текущей сметы (можно /rate работы 10)\n\n"
    "Позиции (в рамках текущей сметы):\n"
    "/add — добавить по шагам\n"
    "/list — список позиций\n"
    "/delete ID — удалить позицию\n"
    "/edit ID [количество] [цена] — изменить\n"
    "/unit ID ед — исправить единицу\n"
    "/generate — Excel по текущей смете\n"
    "/clear — очистить позиции текущей сметы (с подтверждением)\n"
)

CATEGORY_PROMPT = "Сначала выбери категорию: «Работа» или «Материал»."
EMPTY_ESTIMATE = "В текущей смете пока пусто. Выбери категорию и добавь позиции."

ASK_NAME = "Что добавляем? Напиши наименование."
ASK_QTY = "Сколько? Можно с единицей: <code>150 м2</code>"
ASK_UNIT = "Единица измерения? Если не важно — «Пропустить»."
ASK_PRICE = "Цена за единицу?"
DRAFT_CANCELLED = "Отменено. Черновик очищен."
BULK_HINT = (
    "Введи позиции построчно: <b>Наименование, количество, цена</b>\n"
    "Пример: <code>Побелка, 150 м2, 3000</code>\n\n"
    "Запятые внутри наименования допустимы — читаю два последних поля как "
    "количество и цену: <code>Гвозди 3,5 мм, 100, 20</code>"
)


def esc(value: object) -> str:
    """Экранирует пользовательский текст для сообщений с parse_mode=HTML."""
    return html.escape(str(value))


def markup_caption(estimate: Estimate) -> str:
    if estimate.markup_work_bp == estimate.markup_material_bp:
        return f"{format_money(estimate.markup_work_rate)}%"
    return (
        f"работы {format_money(estimate.markup_work_rate)}%, "
        f"материалы {format_money(estimate.markup_material_rate)}%"
    )


def category_title(category: str) -> str:
    return "Материалы и расходники" if category == "Материал" else "Работы"


def render_estimate(
    estimate: Estimate, rows: list[Position], totals: EstimateTotals
) -> str:
    """Сообщение /list. Итог берётся из totals, суммирования в шаблоне нет."""
    out = [f"<b>{esc(estimate.name)}</b> (№{estimate.number})"]
    current = None
    # strict=True: если длины разошлись, это баг расчёта, а не повод молча урезать.
    for row, line in zip(rows, totals.lines, strict=True):
        if row.category != current:
            current = row.category
            out.append(f"\n<b>{category_title(current)}</b>")
        quantity = f"{format_qty(row.qty)} {row.unit}".strip()
        out.append(
            f"#{row.id}: {esc(row.name)}\n"
            f"    Кол-во: {quantity}  Цена: {format_money(row.price)}  "
            f"Сумма: {format_money(line.total)}"
        )
    out.append(f"\nБез наценки: {format_money(totals.subtotal)}")
    out.append(f"Наценка ({markup_caption(estimate)}): {format_money(totals.markup)}")
    out.append(f"Итого: <b>{format_money(totals.total)}</b>")
    out.append(f"Наименований: <b>{len(rows)}</b>")
    return "\n".join(out)


def render_summary(estimate: Estimate, totals: EstimateTotals, is_active: bool) -> str:
    mark = " (активная)" if is_active else ""
    return (
        f"№{estimate.number}: {estimate.name}{mark}\n"
        f"Позиции: {len(totals.lines)}  Итого: {format_money(totals.total)}"
    )


def render_units_substituted(names: list[str], unit: str) -> str:
    """Подстановка единицы обязана быть видимой, а не тихой."""
    listed = ", ".join(names[:5]) + ("…" if len(names) > 5 else "")
    return f"Единица не указана — поставила «{unit}» для: {listed}. Поправить: /unit ID ед"


def render_draft(state, line_total: Decimal) -> str:
    """Предпросмотр перед добавлением: в смету ничего не попадает без показа."""
    quantity = f"{format_qty(state.draft_qty)} {state.draft_unit or ''}".strip()
    return (
        f"<b>{esc(state.draft_name)}</b>\n"
        f"{quantity} × {format_money(state.draft_price)} = "
        f"<b>{format_money(line_total)}</b> с наценкой\n\n"
        f"Добавляем?"
    )


def render_readings(line: str, plain, merged) -> str:
    """Оба прочтения показываются целиком — выбирает человек (ADR-011)."""
    def describe(position) -> str:
        return (
            f"«{esc(position.name)}», {format_qty(position.qty)} {position.unit or ''}".rstrip()
            + f" × {format_money(position.price)}"
        )

    return (
        f"Строку <code>{esc(line)}</code> можно прочитать двумя способами — "
        f"запятая тут и разделитель полей, и десятичный знак.\n\n"
        f"<b>Вариант 1:</b> {describe(plain)}\n"
        f"<b>Вариант 2:</b> {describe(merged)}\n\n"
        f"Что имелось в виду?"
    )


def render_rates(estimate, totals) -> str:
    return (
        f"Наценка сметы «{esc(estimate.name)}» (№{estimate.number}): "
        f"{markup_caption(estimate)}\n"
        f"Итого: <b>{format_money(totals.total)}</b> "
        f"(без наценки {format_money(totals.subtotal)})"
    )
