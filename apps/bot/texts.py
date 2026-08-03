"""Текст сообщений. Арифметики здесь нет: суммы приходят из calculate_estimate."""

import html
from decimal import Decimal

from smeta_core import STATUS_LABEL, EstimateTotals, format_money, format_qty
from smeta_prices import display_unit
from smeta_storage import Estimate, Position

START_TEXT = (
    "Привет! Я бот для расчёта смет.\n\n"
    "📌 Как пользоваться:\n"
    "— Нажми <b>«Начнём»</b> и выбери категорию\n"
    "— Дальше по шагам: наименование → количество → единица → цена\n"
    "— Или списком, если так быстрее: <code>Побелка, 150 м2, 3000</code>\n"
    "— Или просто наговори голосовое и пришли фото накладной — покажу, что "
    "поняла, и добавлю только после твоего «Добавить»\n\n"
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
    "/pdf — PDF по текущей смете\n"
    "/clear — очистить позиции текущей сметы (с подтверждением)\n\n"
    "Заказчику:\n"
    "/send — отправить: смета замораживается, появляется ссылка\n"
    "/link — открыли ли смету и когда, согласована ли\n"
    "/relink — новая ссылка взамен потерянной (старая закроется)\n"
    "/revise — новая редакция отправленной сметы\n"
    "/revoke — закрыть ссылку\n"
)

# Одна формулировка на все поверхности: /list, /generate и /pdf обязаны
# отказывать одинаково, иначе человек увидит сумму в списке и необъяснимый
# отказ в документе — ровно то расхождение, ради которого затевался Sprint 1.
INTEGRITY_BROKEN = (
    "Данные сметы разошлись с тем, что было заморожено при отправке.\n{reason}\n"
    "Документ по ней не выдаётся. Что делать: /revise — новая редакция."
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


# Категории в коде английские; на экран их переводит адаптер.
CATEGORY_LABEL = {"work": "Работа", "material": "Материал"}

# Статус сметы на экране переехал в ядро (smeta_core.STATUS_LABEL): его читают
# бот, PDF и публичная страница, и три копии словаря разошлись бы.


def describe_version(estimate: Estimate) -> str:
    """«ред. 2 — отправлена заказчику». Словами человека, а не домена.

    В базе статус называется `superseded`, и это правильно: значения статусов
    английские, потому что это код. Но прорабу показывать их нельзя — он не
    обязан знать, что такое superseded, а без подписи две сметы «№1» в списке
    неразличимы.
    """
    status = STATUS_LABEL.get(estimate.status, estimate.status).lower()
    return f"ред. {estimate.version} — {status}"


def category_title(category: str) -> str:
    return "Материалы и расходники" if category == "material" else "Работы"


def render_estimate(
    estimate: Estimate, rows: list[Position], totals: EstimateTotals
) -> str:
    """Сообщение /list. Итог берётся из totals, суммирования в шаблоне нет."""
    out = [
        f"<b>{esc(estimate.name)}</b> (№{estimate.number}, {describe_version(estimate)})"
    ]
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
        f"№{estimate.number}, {describe_version(estimate)}{mark}\n"
        f"{estimate.name}\n"
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
    """
    if not row.hint_price:
        return ""
    unit = display_unit(row.unit, row.unit_spoken)
    per = f"/{esc(unit)}" if unit else ""
    when = f"{row.hint_on.day} {MONTHS[row.hint_on.month - 1]}" if row.hint_on else ""
    parts = [f"    💡 вы брали по {format_money(Decimal(row.hint_price))} ₽{per}"]
    tail = ", ".join(part for part in (when, _times(row.hint_times or 1)) if part)
    if tail:
        parts.append(f" — {tail} за полгода")
    if row.hint_median:
        parts.append(f"; чаще всего {format_money(Decimal(row.hint_median))}")
    return "".join(parts)


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


def render_rates(estimate, totals) -> str:
    return (
        f"Наценка сметы «{esc(estimate.name)}» (№{estimate.number}): "
        f"{markup_caption(estimate)}\n"
        f"Итого: <b>{format_money(totals.total)}</b> "
        f"(без наценки {format_money(totals.subtotal)})"
    )
