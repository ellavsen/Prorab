"""Текст сообщений. Арифметики здесь нет: суммы приходят из calculate_estimate."""

import html
from decimal import Decimal

from smeta_core import (
    MARKUP_WORD,
    RATE_OF,
    STATUS_LABEL,
    Category,
    EstimateTotals,
    PositionData,
    RateBase,
    calculate_estimate,
    format_money,
    format_qty,
)
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
    "/rate 6 — ставка текущей сметы (можно /rate работы 10)\n"
    "/basis — от чего считается процент: к цене или от суммы\n\n"
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
    """Ставки вместе с основанием. Одно без другого двусмысленно (ADR-024)."""
    of = RATE_OF[RateBase(estimate.rate_base)]
    if estimate.markup_work_bp == estimate.markup_material_bp:
        return f"{format_money(estimate.markup_work_rate)}% {of}"
    return (
        f"работы {format_money(estimate.markup_work_rate)}%, "
        f"материалы {format_money(estimate.markup_material_rate)}% — {of}"
    )


def markup_title(estimate: Estimate) -> str:
    """«Наценка» или «По договору» — с большой буквы, началом строки."""
    return MARKUP_WORD[RateBase(estimate.rate_base)].capitalize()


# Круглая цена, на которой показывается разница между основаниями. Число для
# человека считается тем же калькулятором, что и деньги в смете: литерал в
# тексте однажды разошёлся бы с расчётом, и именно на том экране, где прораб
# решает про чужие деньги.
EXAMPLE_PRICE = Decimal("1000.00")
EXAMPLE_RATE = Decimal("6.00")


def basis_example(base: str) -> str:
    """«1 060,00» или «1 063,83» — во что превращается тысяча исполнителя."""
    totals = calculate_estimate(
        [PositionData(Category.WORK, "пример", Decimal("1"), EXAMPLE_PRICE)],
        EXAMPLE_RATE, EXAMPLE_RATE, base,
    )
    return format_money(totals.total)


def basis_effect(base: str) -> str:
    """Одна строка про эффект: не термин, а числа."""
    return (
        f"Исполнителю {format_money(EXAMPLE_PRICE)} ₽ → "
        f"заказчику {basis_example(base)} ₽ при {format_money(EXAMPLE_RATE)}%."
    )


# Единственный экран, где прораб решает про деньги заказчика. Ни «наценки», ни
# «удержания», ни «маржи»: он читает их как синонимы, и различить основания они
# не помогают. Ни «рекомендуем», ни «правильно»: какой у него договор, знает он.
# Проверки умножением («6% от 1 060») тоже нет — на смете она не сходится
# (money.md §3.5).
BASIS_FIRST_LEAD = "Один раз спрошу про процент — дальше он подставляется сам.\n\n"

BASIS_FIRST = (
    "«{rate}%» считают двумя разными способами, и разница видна на деньгах.\n"
    "Исполнителю {price} ₽ при ставке {rate}%:\n\n"
    "<code>    к цене     →  заказчику {cost} ₽\n"
    "    от суммы   →  заказчику {price_based} ₽</code>\n\n"
    "«От суммы» — это когда процент удерживают из выставленной суммы: так "
    "обычно записано в договоре с заказчиком. Посчитаешь первым способом — "
    "исполнитель получит меньше, чем назвал.\n\n"
    "Поменять можно до отправки сметы, командой /basis."
)

BASIS_SET = (
    "Процент: {caption}.\n{effect}\n"
    "Новые сметы будут создаваться так же. Поменять: /basis"
)

BASIS_SHOWN = "Смета №{number} «{name}»: {caption}.\n{effect}\n\nПоменять: /basis {other}"

BASIS_UNCLEAR = "Не понял. Два варианта: /basis к цене или /basis от суммы"

# Подстановка из прошлой сметы: молча, но названа. Номер прошлой сметы здесь
# не для красоты — если подставилось не то, это видно сразу, а не на отправке.
# Связка точкой, а не тире: при разных ставках по категориям caption сам
# содержит тире, и «— к цене — как в №1» читается как обрывок.
INHERITED = "Процент: {caption}. Как в №{number}."


def basis_question(first: bool) -> str:
    """Тот же разбор с числами, но «один раз спрошу» — только в первый раз.

    По кнопке «Поменять процент» человек приходит сюда сам и в третий раз;
    обещание спросить однократно там читается как поломка.
    """
    lead = BASIS_FIRST_LEAD if first else ""
    return lead + BASIS_FIRST.format(
        rate=format_money(EXAMPLE_RATE),
        price=format_money(EXAMPLE_PRICE),
        cost=basis_example(RateBase.COST),
        price_based=basis_example(RateBase.PRICE),
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
    out.append(f"\nБез надбавки: {format_money(totals.subtotal)}")
    out.append(
        f"{markup_title(estimate)} ({markup_caption(estimate)}): "
        f"{format_money(totals.markup)}"
    )
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
        f"<b>{format_money(line_total)}</b> с надбавкой\n\n"
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
        f"Надбавка сметы «{esc(estimate.name)}» (№{estimate.number}): "
        f"{markup_caption(estimate)}\n"
        f"Итого: <b>{format_money(totals.total)}</b> "
        f"(без надбавки {format_money(totals.subtotal)})"
    )
