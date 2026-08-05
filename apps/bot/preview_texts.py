"""Тексты распознавания и предпросмотра.

Отдельно от texts.py по границе, а не по объёму: здесь всё, что показывается
между моделью и сметой — услышанное, разобранное, подсказка цены, деление
«за всё». Ни одна строка отсюда ещё не деньги в смете (ADR-012).
"""

from decimal import Decimal

from smeta_core import format_money, format_qty
from smeta_prices import display_unit

from .texts import CATEGORY_LABEL, esc, markup_caption

AI_LISTENING = "Слушаю голосовое…"
AI_LOOKING = "Смотрю накладную…"
AI_NOTHING = (
    "Позиций тут не нашла. Попробуй сказать так: «побелка 150 квадратов по 3000, "
    "гвозди 1000 штук по 20» — или добавь по шагам: /add"
)
AI_DEMO_NOTE = (
    "⚙️ DEMO-режим: ключа OPENAI_API_KEY нет, поэтому распознаёт не модель, "
    "а стаб. Всё остальное — настоящее."
)
AI_FAILED = "Не получилось распознать: {reason}\nМожно добавить по шагам: /add"
PREVIEW_CANCELLED = "Предпросмотр отменён. В смету ничего не добавлено."
PREVIEW_GONE = (
    "Этот предпросмотр уже закрыт — похоже, кнопку нажали дважды или сообщение "
    "осталось от прошлого разговора. Что в смете: /list"
)
PREVIEW_KEPT = "Распознанное не потеряно: сделайте /revise и нажмите «Добавить» снова."



def render_recognized(text: str) -> str:
    """Услышанное показывается целиком: человек должен видеть, что разобрали."""
    return f"Услышала: <i>{esc(text)}</i>"


def render_split(name: str, count, each, restored, delta, total, unit: str) -> str:
    """Что будет при делении «за всё» — до нажатия, а не после.

    Потеря копеек показывается числом: человек сказал одну сумму, а получит
    другую, и решать это ему (ADR-012).
    """
    quantity = f"{format_qty(count)} {unit}".strip()
    lines = [
        f"<b>{esc(name)}</b>\n"
        f"Сказано: {format_money(total)} за всё ({quantity}).\n\n"
        f"Если разбить: {quantity} × {format_money(each)} = "
        f"<b>{format_money(restored)}</b>"
    ]
    if delta:
        direction = "меньше" if delta > 0 else "больше"
        lines.append(f"⚠️ Это на {format_money(abs(delta))} {direction} названного.")
    else:
        lines.append("Сумма сходится копейка в копейку.")
    lines.append("\nРазбить или оставить одной строкой?")
    return "\n".join(lines)


MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря")


def _times(count: int) -> str:
    """«4 раза», «1 раз», «11 раз» — по-русски, а не «4 раз(а)»."""
    tail = count % 100
    if 11 <= tail <= 14:
        return f"{count} раз"
    return {1: f"{count} раз", 2: f"{count} раза",
            3: f"{count} раза", 4: f"{count} раза"}.get(count % 10, f"{count} раз")


def render_price_hint(row) -> str:
    """Что человек сам платил за это раньше. Ни одного выдуманного числа.

    «За полгода» — не оборот речи: выборка ограничена окном истории, и всё,
    что старше, в подсказку не попадает вовсе (ADR-018).

    Цены разошлись — показывается разброс, а не одно число: «брали по 1100»
    при истории 450 / 700 / 1100 правда про последнюю покупку и неправда про
    то, сколько это стоит (ADR-026). Последняя цена при этом не пропадает —
    она уходит во вторую строку и там подписана датой, потому что кнопка
    предлагает именно её.
    """
    if not row.hint_times:
        return ""
    unit = display_unit(row.unit, row.unit_spoken)
    per = f"/{esc(unit)}" if unit else ""
    when = f"{row.hint_on.day} {MONTHS[row.hint_on.month - 1]}" if row.hint_on else ""
    spread = row.hint_low and row.hint_high and row.hint_low != row.hint_high

    if not spread:
        parts = [f"    💡 вы брали по {format_money(Decimal(row.hint_price))} ₽{per}"]
        tail = ", ".join(part for part in (when, _times(row.hint_times or 1)) if part)
        if tail:
            parts.append(f" — {tail} за полгода")
        if row.hint_median:
            parts.append(f"; чаще всего {format_money(Decimal(row.hint_median))}")
        return "".join(parts)

    lines = [
        f"    💡 вы платили от {format_money(Decimal(row.hint_low))} "
        f"до {format_money(Decimal(row.hint_high))} ₽{per} — "
        f"{_times(row.hint_times or 1)} за полгода"
    ]
    if row.hint_price:
        latest = f"последняя {format_money(Decimal(row.hint_price))}"
        if when:
            latest += f", {when}"
    else:
        # Кнопки «Последняя» здесь тоже не будет. Пустое место без причины
        # выглядело бы поломкой, поэтому причина названа.
        latest = "последняя не определена: цены названы в один день"
        if when:
            latest += f", {when}"
    if row.hint_median:
        latest += f"; чаще всего {format_money(Decimal(row.hint_median))}"
    lines.append(f"       {latest}")
    return "\n".join(lines)


def render_pending(estimate, rows, computed: dict, totals) -> str:
    """Предпросмотр распознанной пачки.

    Ни одна строка отсюда ещё не в смете. Позиции, не прошедшие проверку
    домена, показываются с причиной, а не выбрасываются молча (ADR-012).
    """
    good = [row for row in rows if row.ordinal in computed]
    out = [
        f"Распознала позиций: <b>{len(rows)}</b>. Наценка {markup_caption(estimate)}.\n"
    ]
    for row in good:
        line = computed[row.ordinal]
        position = line.position
        # Показываем сказанное: человек должен узнать свои слова (ADR-015).
        spoken = position.unit_spoken or position.unit
        quantity = f"{format_qty(position.qty)} {spoken}".strip()
        # Модель не поняла, за единицу цена или за всё. Считаем за единицу —
        # третьей ветки расчёта нет, — но говорим об этом вслух.
        unclear = " ⚠️ если это за всё — нажми «÷»" if row.price_scope == "unknown" else ""
        out.append(
            f"{row.ordinal}. {esc(position.name)} — "
            f"{esc(CATEGORY_LABEL.get(position.category, position.category)).lower()}\n"
            f"    {quantity} × {format_money(position.price)} = "
            f"<b>{format_money(line.total)}</b>{unclear}"
        )

    broken = [row for row in rows if row.ordinal not in computed]
    if broken:
        out.append("\nНе разобрала:")
        for row in broken:
            out.append(
                f"⚠️ {row.ordinal}. {esc(row.name)} — "
                f"{esc(row.problem or 'непонятная строка')}"
            )
            hint = render_price_hint(row)
            if hint:
                out.append(hint)

    if good:
        out.append(f"\nИтого по этим позициям: <b>{format_money(totals.total)}</b>")
    out.append("\nВ смету пока ничего не добавлено. Добавляем?")
    return "\n".join(out)


