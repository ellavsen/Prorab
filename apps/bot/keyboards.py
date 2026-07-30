"""Клавиатуры. Каждый callback_data, который здесь появляется, обрабатывается."""

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


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
