"""Текст сообщений. Арифметики здесь нет: суммы приходят из calculate_estimate."""

import html
from decimal import Decimal

from smeta_core import STATUS_LABEL, EstimateTotals, format_money, format_qty
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


# Кнопка из прошлого разговора. Молчать в ответ нельзя: человек нажмёт ещё
# несколько раз и решит, что сломан бот, а не устарело сообщение.
STALE_BUTTON = "Кнопка устарела — сообщение из прошлого разговора."
DRAFT_GONE = f"{STALE_BUTTON} Начать ввод заново: /add"


def render_rates(estimate, totals) -> str:
    return (
        f"Наценка сметы «{esc(estimate.name)}» (№{estimate.number}): "
        f"{markup_caption(estimate)}\n"
        f"Итого: <b>{format_money(totals.total)}</b> "
        f"(без наценки {format_money(totals.subtotal)})"
    )
