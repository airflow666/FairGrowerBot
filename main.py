import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, InlineQueryHandler, CallbackQueryHandler, ChosenInlineResultHandler
import database
import handlers

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не найден. Проверьте файл .env")

    database.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Inline — показывает кнопки команд
    app.add_handler(InlineQueryHandler(handlers.inline_query))

    # ChosenInlineResult — даёт РЕАЛЬНЫЙ chat_id группы
    app.add_handler(ChosenInlineResultHandler(handlers.chosen_inline_result))

    # Кнопки — выполняют команды
    app.add_handler(CallbackQueryHandler(handlers.handle_button))

    print("Бот запущен...")
    print("Используй @username_бота в любом чате!")
    app.run_polling()


if __name__ == "__main__":
    main()
