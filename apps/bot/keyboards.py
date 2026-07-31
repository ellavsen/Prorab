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


def readings_keyboard() -> InlineKeyboardMarkup:
    """Выбор прочтения неоднозначной строки. Молча выбирать нельзя (ADR-011)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Вариант 1", callback_data="pick:plain")],
        [InlineKeyboardButton("Вариант 2", callback_data="pick:merged")],
        [InlineKeyboardButton("Отменить строку", callback_data="pick:cancel")],
    ])
