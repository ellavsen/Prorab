"""Сборка приложения и точка входа."""

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .config import require_token
from .handlers import ai, estimates, files, positions, share, stepwise
from .handlers.callbacks import on_callback
from .handlers.errors import on_error


def build_app():
    app = ApplicationBuilder().token(require_token()).build()

    app.add_handler(CommandHandler("start", estimates.start))
    app.add_handler(CommandHandler("help", estimates.help_command))

    app.add_handler(CommandHandler("new", estimates.cmd_new))
    app.add_handler(CommandHandler("estimates", estimates.cmd_estimates))
    app.add_handler(CommandHandler("switch", estimates.cmd_switch))
    app.add_handler(CommandHandler("rate", estimates.cmd_rate))

    app.add_handler(CommandHandler("add", stepwise.cmd_add))
    app.add_handler(CommandHandler("list", positions.cmd_list))
    app.add_handler(CommandHandler("unit", positions.cmd_unit))
    app.add_handler(CommandHandler("delete", positions.cmd_delete))
    app.add_handler(CommandHandler("edit", positions.cmd_edit))
    app.add_handler(CommandHandler("clear", positions.cmd_clear))
    app.add_handler(CommandHandler("generate", files.cmd_generate))
    app.add_handler(CommandHandler("pdf", files.cmd_pdf))

    # Документооборот: отправка замораживает смету, ревизия открывает новую.
    app.add_handler(CommandHandler("send", share.cmd_send))
    app.add_handler(CommandHandler("revise", share.cmd_revise))
    app.add_handler(CommandHandler("link", share.cmd_link))
    app.add_handler(CommandHandler("relink", share.cmd_relink))
    app.add_handler(CommandHandler("revoke", share.cmd_revoke))

    # Кнопки и категории, регистронезависимо.
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^начнём$"), estimates.handle_begin))
    app.add_handler(
        MessageHandler(filters.Regex(r"(?i)^(работа|материал)$"), estimates.handle_category)
    )

    # Голос и фото — отдельных команд нет, бот сам понимает, что прислали.
    app.add_handler(MessageHandler(filters.VOICE, ai.on_voice))
    app.add_handler(MessageHandler(filters.PHOTO, ai.on_photo))

    # Свободный текст: шаг пошагового ввода либо строки позиций.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, positions.on_text))

    app.add_handler(CallbackQueryHandler(on_callback))
    # Один перехват на всё приложение: отказ охраны должен доходить до
    # человека с любого пути записи, а не только с тех, где о нём вспомнили.
    app.add_error_handler(on_error)
    return app


def main() -> None:
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
