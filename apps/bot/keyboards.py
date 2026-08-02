"""Клавиатуры. Каждый callback_data, который здесь появляется, обрабатывается."""

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from smeta_core import UNITS

UNITS_PER_ROW = 4


def start_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Начнём")]], resize_keyboard=True, one_time_keyboard=True
    )


def categories_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("Работа"), KeyboardButton("Материал")]], resize_keyboard=True
    )


def renew_keyboard(estimate_id: int, number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"Обновить смету №{number}", callback_data=f"renew:{estimate_id}")
    ]])


def confirm_keyboard(prefix: str, estimate_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Да", callback_data=f"{prefix}_yes:{estimate_id}"),
        InlineKeyboardButton("Нет", callback_data=f"{prefix}_no:{estimate_id}"),
    ]])


def mode_keyboard() -> InlineKeyboardMarkup:
    """Пошаговый ввод — путь по умолчанию, списком — быстрый (ADR-010)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить по шагам", callback_data="mode:step")],
        [InlineKeyboardButton("Ввести списком", callback_data="mode:bulk")],
    ])


def units_keyboard() -> InlineKeyboardMarkup:
    """Справочник единиц кнопками — иначе о «компл» и «час» никто не узнает."""
    rows = [
        [InlineKeyboardButton(unit, callback_data=f"unit:{unit}") for unit in chunk]
        for chunk in (UNITS[i:i + UNITS_PER_ROW] for i in range(0, len(UNITS), UNITS_PER_ROW))
    ]
    rows.append([InlineKeyboardButton("Пропустить", callback_data="unit:-")])
    return InlineKeyboardMarkup(rows)


def draft_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Добавить", callback_data="draft:add"),
        InlineKeyboardButton("Заново", callback_data="draft:restart"),
        InlineKeyboardButton("Отменить", callback_data="draft:cancel"),
    ]])


DROPS_PER_ROW = 5


def _chunked(values: list[int]):
    return (values[i:i + DROPS_PER_ROW] for i in range(0, len(values), DROPS_PER_ROW))


def pending_keyboard(
    ordinals: list[int], addable: int, splittable: list[int] | None = None,
    hinted: list[int] | None = None, hinted_median: list[int] | None = None,
) -> InlineKeyboardMarkup:
    """Предпросмотр распознанной пачки: убрать лишнее, добавить остальное.

    Кнопки «Добавить» нет, когда добавлять нечего: она обещала бы действие,
    которого не будет. «÷» появляется только у строк, сказанных «за всё»,
    а «взять цену» — только там, где своя история эту цену помнит.
    """
    rows = [
        [InlineKeyboardButton(f"🗑 {o}", callback_data=f"ai:drop:{o}") for o in chunk]
        for chunk in _chunked(ordinals)
    ]
    for chunk in _chunked(splittable or []):
        rows.append([
            InlineKeyboardButton(f"÷ {o}", callback_data=f"ai:split:{o}") for o in chunk
        ])
    for chunk in _chunked(hinted or []):
        rows.append([
            InlineKeyboardButton(f"💡 Взять цену {o}", callback_data=f"ai:hint:{o}")
            for o in chunk
        ])
    for chunk in _chunked(hinted_median or []):
        rows.append([
            InlineKeyboardButton(f"Медиана {o}", callback_data=f"ai:hintmed:{o}")
            for o in chunk
        ])

    tail = []
    if addable:
        tail.append(InlineKeyboardButton(f"✅ Добавить {addable}", callback_data="ai:add"))
    tail.append(InlineKeyboardButton("Отменить", callback_data="ai:cancel"))
    rows.append(tail)
    return InlineKeyboardMarkup(rows)


def split_keyboard(ordinal: int) -> InlineKeyboardMarkup:
    """Разбить «за всё» на позиции. Потеря копеек показана до нажатия."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Разбить", callback_data=f"ai:dosplit:{ordinal}"),
        InlineKeyboardButton("Оставить как есть", callback_data="ai:back"),
    ]])


def readings_keyboard() -> InlineKeyboardMarkup:
    """Выбор прочтения неоднозначной строки. Молча выбирать нельзя (ADR-011)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Вариант 1", callback_data="pick:plain")],
        [InlineKeyboardButton("Вариант 2", callback_data="pick:merged")],
        [InlineKeyboardButton("Отменить строку", callback_data="pick:cancel")],
    ])
