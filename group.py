"""Групповой режим: бот добавлен в чат участником.

В этом режиме доступны обычные команды (/grow, /top, …) и проактивные
сообщения (авто-«писюн дня»). Команды переиспользуют ту же логику, что и
inline-кнопки, — функции ``handlers.cmd_*`` канало-независимы.
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType, ParseMode
from telegram.ext import ContextTypes

import database
import handlers
from game import boss
from utils import format_mention

logger = logging.getLogger(__name__)

_IN_CHAT = {
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
}

WELCOME_TEXT = (
    "🍆 <b>Привет! Я FairGrowerBot.</b>\n\n"
    "Теперь можно играть прямо в группе командами:\n"
    "🎮 /menu — <b>единое меню: вся игра в одном сообщении</b>\n"
    "📈 /grow — вырастить пиписю (раз в сутки)\n"
    "👤 /profile — персонаж: класс, уровень, статы\n"
    "🗺️ /expedition — отправить героя за добычей\n"
    "🎒 /inventory — предметы и экипировка\n"
    "🐉 /boss — сразиться с боссом чата\n"
    "🏰 /dungeon — рискнуть в подземелье\n"
    "🏪 /shop — магазин: сундуки и смена класса\n"
    "🏡 /farm — пассивный доход\n"
    "🏆 /top — топ участников\n"
    "📅 /weektop — топ прироста за неделю\n"
    "🎉 /dickofday — писюн дня\n"
    "📊 /stats — твоя статистика\n"
    "⚔️ /duel — дуэль на сантиметры\n"
    "🎰 /casino — испытать удачу\n\n"
    "Нажми кнопку ниже, чтобы активировать чат и подключить статистику, "
    "которую вы уже наиграли через inline-режим 👇"
)

HELP_TEXT = (
    "🍆 <b>FairGrowerBot</b>\n\n"
    "👉 Жми <b>/menu</b> — там вся движуха в одном сообщении:\n"
    "рост, топы, дуэли, казино, а во втором этаже «🎮 RPG» — "
    "персонаж, лут, боссы и подземелья.\n\n"
    "Работает и через inline: <code>@имя_бота</code> в любом чате."
)


# --- Добавление/удаление бота из чата ---------------------------------------

async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Реакция на изменение статуса самого бота в чате."""
    result = update.my_chat_member
    if result is None or result.new_chat_member.user.id != context.bot.id:
        return
    chat = result.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    was_in = result.old_chat_member.status in _IN_CHAT
    now_in = result.new_chat_member.status in _IN_CHAT

    if now_in and not was_in:
        database.record_chat(chat.id, chat.title)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Активировать чат", callback_data="link_stats")]]
        )
        try:
            await context.bot.send_message(
                chat.id, WELCOME_TEXT, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось отправить приветствие в чат %s", chat.id)
    elif was_in and not now_in:
        database.set_chat_active(chat.id, False)
        logger.info("Бота удалили из чата %s", chat.id)


# --- Команды в группе -------------------------------------------------------

async def _reply(update: Update, result):
    text, markup = result if isinstance(result, tuple) else (result, None)
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=markup
    )


def _chat_key(update: Update) -> str:
    return str(update.effective_chat.id)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единое меню: вся игра в одном сообщении, навигация кнопками."""
    await _reply(update, handlers.cmd_menu(_chat_key(update), update.effective_user))


async def cmd_grow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_grow(_chat_key(update), update.effective_user))


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_profile(_chat_key(update), update.effective_user))


async def cmd_expedition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_expedition(_chat_key(update), update.effective_user))


async def cmd_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_inventory(_chat_key(update), update.effective_user))


async def cmd_boss(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_boss(_chat_key(update), update.effective_user))


async def cmd_dungeon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_dungeon(_chat_key(update), update.effective_user))


async def cmd_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_shop(_chat_key(update), update.effective_user))


async def cmd_farm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_farm(_chat_key(update), update.effective_user))


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_top(_chat_key(update)))


async def cmd_weektop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_weektop(_chat_key(update)))


async def cmd_dickofday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_dickofday(_chat_key(update)))


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_stats(_chat_key(update), update.effective_user))


async def cmd_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_duel(_chat_key(update), update.effective_user))


async def cmd_casino(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, handlers.cmd_casino(_chat_key(update), update.effective_user))


# --- Проактивные события ----------------------------------------------------

async def spawn_bosses(context: ContextTypes.DEFAULT_TYPE):
    """Заспавнить босса во всех активных чатах без активного босса."""
    for chat in database.get_active_chats():
        chat_id = chat["chat_id"]
        try:
            if database.get_active_boss(chat_id):
                continue
            active, is_new = boss.summon(chat_id)
            if not is_new:
                continue
            text, markup = handlers.boss_message(active)
            await context.bot.send_message(int(chat_id), text,
                                           parse_mode=ParseMode.HTML,
                                           reply_markup=markup)
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось заспавнить босса в чате %s", chat_id)


async def auto_dick_of_day(context: ContextTypes.DEFAULT_TYPE):
    """Выбрать писюна дня во всех активных чатах (запускается в полночь)."""
    for chat in database.get_active_chats():
        chat_id = chat["chat_id"]
        try:
            if database.get_current_dick_of_day(chat_id):
                continue
            result = database.set_dick_of_day(chat_id)
            if not result:
                continue
            name = format_mention(result["user_id"], result["username"],
                                  result["first_name"])
            text = (
                f"🎉 <b>Писюн дня:</b> {name}!\n"
                f"🎁 Бонус: <b>+{result['bonus']} см</b>\n"
                f"📏 Новый размер: <b>{result['new_size']} см</b>"
            )
            await context.bot.send_message(int(chat_id), text,
                                           parse_mode=ParseMode.HTML)
        except Exception:  # noqa: BLE001
            logger.exception("Не удалось выбрать писюна дня для чата %s", chat_id)
