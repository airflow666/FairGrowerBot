"""Обработчики inline-запросов и callback-кнопок.

Бот работает в inline-режиме: пользователь вызывает его через ``@bot`` в чате,
выбирает команду, а результат показывается прямо в сообщении по нажатию кнопки.
Идентификатор чата (``chat_key``) берётся из callback-запроса: реальный
``chat.id`` (если бот в группе) либо ``chat_instance`` для inline-сообщений.
"""
import logging
import random

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import config
import database
from utils import format_mention

logger = logging.getLogger(__name__)

THUMB_URL = "https://img.icons8.com/emoji/48/000000/eggplant-emoji.png"

# Пункты меню inline-режима: (id, заголовок, описание)
MENU = [
    ("grow", "📈 Grow", "Увеличить пиписю"),
    ("top", "🏆 Top", "Топ участников"),
    ("weektop", "📅 Топ недели", "Прирост за 7 дней"),
    ("dickofday", "🎉 Dick Of Day", "Писюн дня"),
    ("stats", "📊 Stats", "Статистика"),
    ("duel", "⚔️ Duel", "Дуэль"),
    ("casino", "🎰 Casino", "Казино"),
]


# --- Инфраструктура ---------------------------------------------------------

def _chat_key(query):
    """Идентификатор чата из callback-запроса."""
    if query.message and query.message.chat:
        return query.message.chat.id
    return query.chat_instance


def _achievement_suffix(user_id, chat_key, candidate_codes):
    """Разблокировать достижения и вернуть текст об их получении."""
    unlocked = [code for code in candidate_codes
                if database.unlock_achievement(user_id, chat_key, code)]
    if not unlocked:
        return ""
    lines = []
    for code in unlocked:
        emoji, title = config.ACHIEVEMENTS.get(code, ("🏅", code))
        lines.append(f"{emoji} <b>{title}</b>")
    return "\n\n🏅 Новое достижение:\n" + "\n".join(lines)


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать меню команд в inline-режиме."""
    results = []
    for cmd_id, title, desc in MENU:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"Нажми чтобы {title.lower()}",
                                   callback_data=f"cmd_{cmd_id}")]]
        )
        results.append(
            InlineQueryResultArticle(
                id=cmd_id,
                title=title,
                description=desc,
                input_message_content=InputTextMessageContent(
                    f"{title}\nНажми кнопку ниже 👇",
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=keyboard,
                thumbnail_url=THUMB_URL,
            )
        )
    await update.inline_query.answer(results, cache_time=0)


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единая точка входа для всех callback-кнопок."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    chat_key = _chat_key(query)
    user = query.from_user

    try:
        if data.startswith("cmd_"):
            await _run_command(query, context, chat_key, data[len("cmd_"):])
        elif data.startswith("create_duel_"):
            await _create_duel(query, context, chat_key, int(data.rsplit("_", 1)[1]))
        elif data.startswith("accept_duel_"):
            await _accept_duel(query, context, chat_key, int(data.rsplit("_", 1)[1]))
        elif data.startswith("casino_"):
            await _play_casino(query, context, chat_key, int(data.rsplit("_", 1)[1]))
    except Exception:  # noqa: BLE001 — не роняем event loop из-за одной кнопки
        logger.exception("Ошибка обработки кнопки %r (user=%s)", data, user.id)
        try:
            await query.answer("⚠️ Что-то пошло не так, попробуй ещё раз", show_alert=True)
        except Exception:  # noqa: BLE001
            pass


async def _run_command(query, context, chat_key, cmd):
    """Выполнить команду меню и обновить сообщение."""
    user = query.from_user
    handlers = {
        "grow": lambda: cmd_grow(chat_key, user),
        "top": lambda: cmd_top(chat_key),
        "weektop": lambda: cmd_weektop(chat_key),
        "dickofday": lambda: cmd_dickofday(chat_key),
        "stats": lambda: cmd_stats(chat_key, user),
        "duel": lambda: cmd_duel(chat_key, user),
        "casino": lambda: cmd_casino(chat_key, user),
    }
    handler = handlers.get(cmd)
    if handler is None:
        return
    text, markup = _as_pair(handler())
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


def _as_pair(result):
    """Привести результат команды к паре (текст, разметка)."""
    if isinstance(result, tuple):
        return result
    return result, None


# --- Команды ----------------------------------------------------------------

def cmd_grow(chat_key, user):
    change = random.randint(config.GROW_MIN, config.GROW_MAX)
    result = database.apply_grow(user_id=user.id, chat_id=chat_key, change=change,
                                 username=user.username, first_name=user.first_name)
    if result is None:
        return (
            f"📈 Ты уже увеличивал сегодня, {user.first_name}!\n"
            f"Приходи после 00:00 🕛"
        )

    change = result["change"]
    new_size = result["new_size"]
    if change > 0:
        text = f"📈 Твоя пипися выросла на <b>+{change} см</b>!"
    elif change < 0:
        text = f"📉 Твоя пипися уменьшилась на <b>{change} см</b>!"
    else:
        text = "➡️ Твоя пипися осталась без изменений!"
    text += f"\n📏 Текущий размер: <b>{new_size} см</b>"
    if result["streak"] > 1:
        text += f"\n🔥 Серия: {result['streak']} дн. подряд"

    codes = ["first_grow"]
    if new_size >= 100:
        codes.append("size_100")
    elif new_size >= 50:
        codes.append("size_50")
    if change == config.GROW_MAX:
        codes.append("jackpot")
    if change == config.GROW_MIN:
        codes.append("unlucky")
    if result["streak"] >= 7:
        codes.append("streak_7")
    text += _achievement_suffix(user.id, chat_key, codes)
    return text


def cmd_top(chat_key):
    top = database.get_chat_top(chat_key, limit=10)
    if not top:
        return "🏆 Пока никто не увеличивал свою пиписю!\nИспользуй Grow первым 🍆"

    msg = "🏆 <b>ТОП самых огромных писюнов:</b>\n\n"
    for i, u in enumerate(top, 1):
        name = format_mention(u["user_id"], u["username"], u["first_name"])
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        msg += f"{medal} {name}: {int(u['size'])} см\n"
    return msg


def cmd_weektop(chat_key):
    top = database.get_weekly_top(chat_key, limit=10)
    top = [u for u in top if u["gain"]]
    if not top:
        return "📅 За последнюю неделю ещё никто не рос!\nИспользуй Grow 🍆"

    msg = "📅 <b>Топ прироста за неделю:</b>\n\n"
    for i, u in enumerate(top, 1):
        name = format_mention(u["user_id"], u["username"], u["first_name"])
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        gain = int(u["gain"])
        sign = "+" if gain >= 0 else ""
        msg += f"{medal} {name}: {sign}{gain} см\n"
    return msg


def cmd_dickofday(chat_key):
    current = database.get_current_dick_of_day(chat_key)
    if current:
        name = format_mention(current["user_id"], current["username"],
                              current["first_name"])
        return (
            f"🎉 <b>Писюн дня уже выбран!</b>\n\n"
            f"🏆 {name}\n"
            f"🎁 Бонус: <b>+{current['bonus']} см</b>\n"
            f"📏 Размер: <b>{int(current['old_size'])} → {int(current['new_size'])} см</b>"
        )

    result = database.set_dick_of_day(chat_key)
    if not result:
        return "😔 Нет участников, чтобы выбрать писюна дня!\nИспользуй Grow первым 🍆"

    name = format_mention(result["user_id"], result["username"], result["first_name"])
    text = (
        f"🎉 <b>Писюн дня:</b> {name}!\n"
        f"🎁 Бонус: <b>+{result['bonus']} см</b>\n"
        f"📏 Новый размер: <b>{result['new_size']} см</b>"
    )
    text += _achievement_suffix(result["user_id"], chat_key, ["dick_of_day"])
    return text


def cmd_stats(chat_key, user):
    stats = database.get_duel_stats(user.id, chat_key)
    size = database.get_user_size(user.id, chat_key)
    user_row = database.get_or_create_user(user.id, chat_key, user.username,
                                           user.first_name)
    total_games = stats["wins"] + stats["losses"]
    winrate = round(stats["wins"] / total_games * 100) if total_games else 0
    achievements = database.get_achievements(user.id, chat_key)

    text = (
        f"📊 <b>Статистика:</b>\n\n"
        f"📏 Текущий размер: <b>{size} см</b>\n"
        f"🚀 Рекорд: <b>{int(user_row['max_size'])} см</b>\n"
        f"🔥 Серия роста: {int(user_row['grow_streak'] or 0)} дн.\n\n"
        f"⚔️ Дуэли:\n"
        f"✅ Побед: {stats['wins']}\n"
        f"❌ Поражений: {stats['losses']}\n"
        f"📈 Винрейт: {winrate}%\n"
        f"💰 Суммарно выиграно: <b>{int(stats['total_won'])} см</b>\n\n"
        f"🏅 Достижений: {len(achievements)}/{len(config.ACHIEVEMENTS)}"
    )
    return text


def cmd_duel(chat_key, user):
    size = database.get_user_size(user.id, chat_key)
    if size <= 0:
        return "😢 Твоя пипися слишком короткая!\nВозвращайся позже 🍆"

    buttons, row = [], []
    for stake in config.DUEL_STAKES:
        if stake <= size:
            row.append(InlineKeyboardButton(f"{stake} см",
                                            callback_data=f"create_duel_{stake}"))
        if len(row) >= 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if not buttons:
        buttons = [[InlineKeyboardButton("1 см", callback_data="create_duel_1")]]

    text = (
        f"⚔️ <b>ДУЭЛЬ</b>\n\n"
        f"💰 Твой размер: <b>{size} см</b>\n\n"
        f"Выбери ставку:"
    )
    return text, InlineKeyboardMarkup(buttons)


def cmd_casino(chat_key, user):
    size = database.get_user_size(user.id, chat_key)
    if size <= 0:
        return "😢 Тебе нечего ставить!\nСначала подрасти через Grow 🍆"

    buttons, row = [], []
    for stake in config.CASINO_STAKES:
        if stake <= size:
            row.append(InlineKeyboardButton(f"{stake} см",
                                            callback_data=f"casino_{stake}"))
        if len(row) >= 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if not buttons:
        buttons = [[InlineKeyboardButton("1 см", callback_data="casino_1")]]

    text = (
        f"🎰 <b>КАЗИНО</b>\n\n"
        f"💰 Твой размер: <b>{size} см</b>\n"
        f"Шанс 50%: ставка ×{config.CASINO_WIN_MULTIPLIER} или сгорает.\n\n"
        f"Выбери ставку:"
    )
    return text, InlineKeyboardMarkup(buttons)


# --- Дуэль: создание и принятие ---------------------------------------------

async def _create_duel(query, context, chat_key, bet):
    user = query.from_user
    size = database.get_user_size(user.id, chat_key)
    if bet > size:
        await query.edit_message_text(
            f"⚠️ Твоя пипися всего {size} см.\nСтавка больше твоего размера!"
        )
        return

    duel_id = database.create_duel(user.id, chat_key, bet, query.inline_message_id)
    name = format_mention(user.id, user.username, user.first_name)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⚔️ Принять вызов!",
                               callback_data=f"accept_duel_{duel_id}")]]
    )
    text = (
        f"⚔️ <b>ДУЭЛЬ!</b>\n\n"
        f"{name} вызывает кого-нибудь на дуэль!\n"
        f"💰 Ставка: <b>{bet} см</b>\n\n"
        f"Нажми кнопку, чтобы принять вызов!"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

    _schedule_duel_timeout(context, duel_id, chat_key, query)


def _schedule_duel_timeout(context, duel_id, chat_key, query):
    if context.job_queue is None:
        return
    context.job_queue.run_once(
        _duel_timeout_job,
        config.DUEL_TIMEOUT,
        name=f"duel_{duel_id}",
        data={
            "duel_id": duel_id,
            "inline_message_id": query.inline_message_id,
            "chat_id": query.message.chat.id if query.message else None,
            "message_id": query.message.message_id if query.message else None,
        },
    )


async def _duel_timeout_job(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    if not database.expire_duel(data["duel_id"]):
        return  # уже принята или истекла
    text = "⌛ <b>Дуэль истекла</b>\n\nНикто не принял вызов вовремя."
    try:
        if data["inline_message_id"]:
            await context.bot.edit_message_text(
                text, inline_message_id=data["inline_message_id"],
                parse_mode=ParseMode.HTML,
            )
        elif data["chat_id"] and data["message_id"]:
            await context.bot.edit_message_text(
                text, chat_id=data["chat_id"], message_id=data["message_id"],
                parse_mode=ParseMode.HTML,
            )
    except Exception:  # noqa: BLE001
        logger.debug("Не удалось обновить истёкшую дуэль %s", data["duel_id"])


async def _accept_duel(query, context, chat_key, duel_id):
    accepter = query.from_user

    duel = database.claim_duel(duel_id, accepter.id)
    if duel is None:
        await query.answer("Дуэль уже завершена или истекла!", show_alert=True)
        return

    challenger_id = duel["challenger_id"]
    bet = int(duel["bet"])

    if accepter.id == challenger_id:
        # Возвращаем дуэль в активное состояние — вызвавший не может принять сам
        database.create_duel(challenger_id, chat_key, bet, duel.get("inline_message_id"))
        await query.answer("Ты не можешь принять свой же вызов!", show_alert=True)
        return

    if database.get_user_size(accepter.id, chat_key) < bet:
        database.create_duel(challenger_id, chat_key, bet, duel.get("inline_message_id"))
        await query.answer("😢 Твоя пипися короче ставки! Возвращайся позже",
                           show_alert=True)
        return

    _cancel_duel_timeout(context, duel_id)

    winner_id, loser_id = database.resolve_duel(challenger_id, accepter.id, chat_key, bet)
    database.get_or_create_user(accepter.id, chat_key, accepter.username,
                                accepter.first_name)

    challenger = database.get_or_create_user(challenger_id, chat_key)
    challenger_name = format_mention(challenger_id, challenger["username"],
                                     challenger["first_name"])
    accepter_name = format_mention(accepter.id, accepter.username, accepter.first_name)
    winner_name = challenger_name if winner_id == challenger_id else accepter_name
    loser_name = accepter_name if winner_id == challenger_id else challenger_name

    text = (
        f"⚔️ <b>РЕЗУЛЬТАТ ДУЭЛИ!</b>\n\n"
        f"{challenger_name} VS {accepter_name}\n"
        f"💰 Ставка: {bet} см\n\n"
        f"🏆 Победитель: {winner_name}! (+{bet} см)\n"
        f"💀 Проигравший: {loser_name}! (-{bet} см)"
    )

    wins = database.get_duel_stats(winner_id, chat_key)["wins"]
    codes = ["duel_win_1"]
    if wins >= 10:
        codes.append("duel_win_10")
    text += _achievement_suffix(winner_id, chat_key, codes)

    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


def _cancel_duel_timeout(context, duel_id):
    if context.job_queue is None:
        return
    for job in context.job_queue.get_jobs_by_name(f"duel_{duel_id}"):
        job.schedule_removal()


# --- Казино -----------------------------------------------------------------

async def _play_casino(query, context, chat_key, bet):
    user = query.from_user
    size = database.get_user_size(user.id, chat_key)
    if bet > size:
        await query.answer("⚠️ Ставка больше твоего размера!", show_alert=True)
        return

    win = random.random() < 0.5
    new_size = database.play_casino(user.id, chat_key, bet, win)
    if win:
        prize = bet * (config.CASINO_WIN_MULTIPLIER - 1)
        text = (
            f"🎰 <b>ПОБЕДА!</b>\n\n"
            f"Ты выиграл <b>+{prize} см</b>! 🎉\n"
            f"📏 Новый размер: <b>{new_size} см</b>"
        )
    else:
        text = (
            f"🎰 <b>МИМО!</b>\n\n"
            f"Ставка <b>{bet} см</b> сгорела 💀\n"
            f"📏 Новый размер: <b>{new_size} см</b>"
        )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
