import logging
from datetime import time

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
)

import config
import database
import group
import handlers
import utils

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

    # Групповой режим: команды и добавление/удаление бота из чата
    app.add_handler(CommandHandler("start", group.cmd_start))
    app.add_handler(CommandHandler("help", group.cmd_help))
    app.add_handler(CommandHandler("grow", group.cmd_grow))
    app.add_handler(CommandHandler("profile", group.cmd_profile))
    app.add_handler(CommandHandler("expedition", group.cmd_expedition))
    app.add_handler(CommandHandler("inventory", group.cmd_inventory))
    app.add_handler(CommandHandler("top", group.cmd_top))
    app.add_handler(CommandHandler("weektop", group.cmd_weektop))
    app.add_handler(CommandHandler("dickofday", group.cmd_dickofday))
    app.add_handler(CommandHandler("stats", group.cmd_stats))
    app.add_handler(CommandHandler("duel", group.cmd_duel))
    app.add_handler(CommandHandler("casino", group.cmd_casino))
    app.add_handler(ChatMemberHandler(group.on_my_chat_member,
                                      ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_error_handler(on_error)

    # Авто-«писюн дня» в полночь по настроенному часовому поясу
    if app.job_queue is not None:
        app.job_queue.run_daily(
            group.auto_dick_of_day,
            time=time(hour=0, minute=0, tzinfo=utils.TZ),
        )
    else:
        logger.warning("JobQueue недоступен — авто-«писюн дня» отключён. "
                       "Установите python-telegram-bot[job-queue].")

    logger.info("Бот запущен. Работает в inline-режиме и в группах.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
