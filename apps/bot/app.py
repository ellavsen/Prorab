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
from .handlers import estimates, files, positions, stepwise
from .handlers.callbacks import on_callback


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

    # Кнопки и категории, регистронезависимо.
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^начнём$"), estimates.handle_begin))
    app.add_handler(
        MessageHandler(filters.Regex(r"(?i)^(работа|материал)$"), estimates.handle_category)
    )

    # Свободный текст: шаг пошагового ввода либо строки позиций.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, positions.on_text))

    app.add_handler(CallbackQueryHandler(on_callback))
    return app


def main() -> None:
    build_app().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
