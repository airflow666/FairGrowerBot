import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    InlineQueryHandler,
)

import config
import database
import handlers

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Логировать необработанные исключения в обработчиках."""
    logger.exception("Необработанная ошибка", exc_info=context.error)


def main():
    if not config.BOT_TOKEN:
        raise ValueError("BOT_TOKEN не найден. Проверьте файл .env")

    database.init_db()

    app = Application.builder().token(config.BOT_TOKEN).build()

    # Inline-меню команд
    app.add_handler(InlineQueryHandler(handlers.inline_query))
    # Все нажатия кнопок
    app.add_handler(CallbackQueryHandler(handlers.handle_button))

    app.add_error_handler(on_error)

    logger.info("Бот запущен. Вызывай через inline: @username_бота")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
