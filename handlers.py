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
from game import (
    boss,
    character,
    classes,
    dungeon,
    economy,
    expeditions,
    leveling,
    loot,
)
from utils import format_mention

logger = logging.getLogger(__name__)

THUMB_URL = "https://img.icons8.com/emoji/48/000000/eggplant-emoji.png"

# Экраны единого меню: (id, кнопка). Порядок задаёт раскладку хаба.
MENU = [
    ("grow", "📈 Grow"),
    ("profile", "👤 Профиль"),
    ("expedition", "🗺️ Экспедиция"),
    ("inventory", "🎒 Инвентарь"),
    ("boss", "🐉 Босс"),
    ("dungeon", "🏰 Подземелье"),
    ("shop", "🏪 Магазин"),
    ("farm", "🏡 Ферма"),
    ("duel", "⚔️ Дуэль"),
    ("casino", "🎰 Казино"),
    ("top", "🏆 Топ"),
    ("weektop", "📅 Топ недели"),
    ("dickofday", "🎉 Писюн дня"),
    ("stats", "📊 Статистика"),
    ("info", "ℹ️ Помощь"),
]


# --- Инфраструктура ---------------------------------------------------------

def _chat_key(query):
    """Канонический идентификатор чата из callback-запроса.

    Для кнопки под обычным сообщением в группе доступны и ``chat.id``, и
    ``chat_instance`` — пользуемся моментом и связываем их (перенос старой
    inline-статистики на реальный chat_id). Для inline-сообщения канонический
    ключ достаём из ранее сохранённой связки.
    """
    if query.message and query.message.chat:
        chat_id = query.message.chat.id
        if query.chat_instance:
            database.link_chat_instance(query.chat_instance, chat_id)
        return str(chat_id)
    return database.resolve_chat_key(query.chat_instance)


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
    """Inline-режим: одна статья «Меню» — вся игра внутри одного сообщения.

    Раньше каждая команда была отдельной статьёй, и каждое действие роняло
    в чат новое сообщение. Теперь навигация происходит кнопками внутри
    одного сообщения — чат не засоряется.
    """
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🎮 Открыть меню", callback_data="open_menu")]]
    )
    results = [
        InlineQueryResultArticle(
            id="menu",
            title="🎮 Меню",
            description="Вся игра в одном сообщении",
            input_message_content=InputTextMessageContent(
                "🎮 <b>FairGrowerBot</b>\nНажми кнопку, чтобы открыть меню 👇",
                parse_mode=ParseMode.HTML,
            ),
            reply_markup=keyboard,
            thumbnail_url=THUMB_URL,
        )
    ]
    await update.inline_query.answer(results, cache_time=0)


async def _answer(query, text=None, alert=False):
    """Ответить на callback ровно один раз.

    Telegram принимает только первый ``answerCallbackQuery`` — повторный
    вызов бросает ошибку и попап не показывается. Поэтому обработчики
    НЕ должны отвечать заранее: каждый путь отвечает один раз через этот
    хелпер, а повторные/поздние ответы просто глотаются.
    """
    try:
        await query.answer(text=text, show_alert=alert)
    except Exception:  # noqa: BLE001 — уже отвечен или запрос истёк
        pass


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Единая точка входа для всех callback-кнопок."""
    query = update.callback_query
    data = query.data or ""
    chat_key = _chat_key(query)
    user = query.from_user

    try:
        if data.startswith("nav_"):
            await _nav(query, context, chat_key, data[len("nav_"):])
        elif data == "open_menu":
            # Первый нажавший становится владельцем меню
            text, markup = cmd_menu(chat_key, user)
            await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                          reply_markup=markup)
        elif data.startswith("cmd_"):
            await _run_command(query, context, chat_key, data[len("cmd_"):])
        elif data.startswith("create_duel_"):
            await _create_duel(query, context, chat_key, int(data.rsplit("_", 1)[1]))
        elif data.startswith("accept_duel_"):
            await _accept_duel(query, context, chat_key, int(data.rsplit("_", 1)[1]))
        elif data.startswith("casino_"):
            await _play_casino(query, context, chat_key, int(data.rsplit("_", 1)[1]))
        elif data.startswith("setclass_"):
            await _set_class(query, context, chat_key, data[len("setclass_"):])
        elif data.startswith("start_exp_"):
            await _start_expedition(query, context, chat_key, data[len("start_exp_"):])
        elif data == "claim_exp":
            await _claim_expedition(query, context, chat_key)
        elif data.startswith("equip_"):
            await _equip_item(query, context, chat_key, int(data.rsplit("_", 1)[1]))
        elif data == "boss_hit":
            await _boss_hit(query, context, chat_key)
        elif data.startswith("boss_hit_"):
            await _boss_hit(query, context, chat_key,
                            owner_id=int(data.rsplit("_", 1)[1]))
        elif data.startswith("dng_enter_"):
            await _dungeon_enter(query, context, chat_key, data[len("dng_enter_"):])
        elif data.startswith("dng_deep_"):
            await _dungeon_deeper(query, context, int(data.rsplit("_", 1)[1]))
        elif data.startswith("dng_leave_"):
            await _dungeon_leave(query, context, int(data.rsplit("_", 1)[1]))
        elif data.startswith("buy_chest_"):
            await _buy_chest(query, context, chat_key, data[len("buy_chest_"):])
        elif data == "shop_reclass":
            await _shop_reclass(query, context, chat_key)
        elif data.startswith("reclass_"):
            await _reclass(query, context, chat_key, data[len("reclass_"):])
        elif data == "claim_income":
            await _claim_income(query, context, chat_key)
        elif data == "upgrade_prop":
            await _upgrade_prop(query, context, chat_key)
        elif data.startswith("sell_"):
            await _sell_item(query, context, chat_key, int(data.rsplit("_", 1)[1]))
        elif data.startswith("sellall_"):
            await _sell_all(query, context, chat_key, data[len("sellall_"):])
        elif data.startswith("convert_"):
            await _convert_cm(query, context, chat_key, int(data.rsplit("_", 1)[1]))
        elif data == "craft_menu":
            await _craft_menu(query, context, chat_key)
        elif data.startswith("craft_"):
            await _craft(query, context, chat_key, data[len("craft_"):])
        elif data == "link_stats":
            # Связка chat_instance ↔ chat_id уже выполнена в _chat_key выше
            await query.edit_message_text(
                "✅ <b>Чат активирован!</b>\n\n"
                "Команды теперь работают и в группе (/grow, /top, /duel, /casino, "
                "/stats), а «писюн дня» будет выбираться автоматически в полночь. "
                "Старая статистика подключена.",
                parse_mode=ParseMode.HTML,
            )
    except Exception:  # noqa: BLE001 — не роняем event loop из-за одной кнопки
        logger.exception("Ошибка обработки кнопки %r (user=%s)", data, user.id)
        await _answer(query, "⚠️ Что-то пошло не так, попробуй ещё раз", alert=True)
    finally:
        # Погасить спиннер на кнопке, если ни один путь не ответил
        await _answer(query)


def _screen(chat_key, user, screen):
    """Отрисовать экран по коду. Возвращает (text, markup) или None."""
    screens = {
        "menu": lambda: cmd_menu(chat_key, user),
        "grow": lambda: cmd_grow(chat_key, user),
        "profile": lambda: cmd_profile(chat_key, user),
        "expedition": lambda: cmd_expedition(chat_key, user),
        "inventory": lambda: cmd_inventory(chat_key, user),
        "boss": lambda: cmd_boss(chat_key, user),
        "dungeon": lambda: cmd_dungeon(chat_key, user),
        "shop": lambda: cmd_shop(chat_key, user),
        "farm": lambda: cmd_farm(chat_key, user),
        "craft": lambda: cmd_craft(chat_key, user),
        "top": lambda: cmd_top(chat_key),
        "weektop": lambda: cmd_weektop(chat_key),
        "dickofday": lambda: cmd_dickofday(chat_key),
        "stats": lambda: cmd_stats(chat_key, user),
        "duel": lambda: cmd_duel(chat_key, user),
        "casino": lambda: cmd_casino(chat_key, user),
        "info": lambda: cmd_info(chat_key, user),
    }
    render = screens.get(screen)
    if render is None:
        return None
    return _as_pair(render())


def _menu_row(owner_id):
    """Кнопка возврата в меню владельца."""
    return [InlineKeyboardButton("⬅️ Меню", callback_data=f"nav_{owner_id}_menu")]


def _with_back(markup, owner_id):
    """Добавить к клавиатуре экрана строку «⬅️ Меню»."""
    rows = list(markup.inline_keyboard) if markup else []
    return InlineKeyboardMarkup([*rows, _menu_row(owner_id)])


def cmd_menu(chat_key, user):
    """Хаб единого меню: все экраны — кнопками, владелец зашит в callback."""
    player = character.get_or_create(user.id, user.username, user.first_name)
    size = database.get_user_size(user.id, chat_key)
    name = format_mention(user.id, user.username, user.first_name)
    text = (
        f"🎮 <b>Меню</b> — {name}\n\n"
        f"⭐ Уровень {player['level']}  🪙 {int(player['coins'])} монет  "
        f"📏 {size} см\n\n"
        f"Выбери раздел (кнопки работают только для тебя):"
    )
    rows, row = [], []
    for screen_id, label in MENU:
        row.append(InlineKeyboardButton(label,
                                        callback_data=f"nav_{user.id}_{screen_id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return text, InlineKeyboardMarkup(rows)


async def _nav(query, context, chat_key, payload):
    """Навигация по единому меню: nav_{owner_id}_{screen}."""
    owner_str, _, screen = payload.partition("_")
    try:
        owner_id = int(owner_str)
    except ValueError:
        return
    user = query.from_user
    if user.id != owner_id:
        await _answer(query, "Это не твоё меню! Открой своё: @бот → Меню",
                      alert=True)
        return
    rendered = _screen(chat_key, user, screen)
    if rendered is None:
        return
    text, markup = rendered
    if screen != "menu":
        markup = _with_back(markup, owner_id)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=markup)


async def _run_command(query, context, chat_key, cmd):
    """Совместимость: кнопки старых сообщений (cmd_*) продолжают работать."""
    rendered = _screen(chat_key, query.from_user, cmd)
    if rendered is None:
        return
    text, markup = rendered
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

    exp = character.grant_exp(user.id, config.EXP_PER_GROW,
                              user.username, user.first_name)
    text += f"\n✨ +{exp['gained']} XP"
    if exp["level_up"] > 0:
        text += f"\n🎉 Новый уровень: <b>{exp['level']}</b>!"
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


def _progress_bar(cur, total, width=10):
    if total <= 0:
        return "▰" * width
    filled = max(0, min(width, round(width * cur / total)))
    return "▰" * filled + "▱" * (width - filled)


def _class_keyboard(owner_id):
    rows = [
        [InlineKeyboardButton(f"{cls['emoji']} {cls['name']} — {cls['perk']}",
                              callback_data=f"setclass_{owner_id}_{code}")]
        for code, cls in config.CLASSES.items()
    ]
    return InlineKeyboardMarkup(rows)


def cmd_profile(chat_key, user):
    player = character.get_or_create(user.id, user.username, user.first_name)
    level, into, need = leveling.progress(player["exp"])
    stats = character.effective_stats(player)
    name = format_mention(user.id, user.username, user.first_name)
    size = database.get_user_size(user.id, chat_key)

    stat_lines = "\n".join(
        f"{config.STATS[s][0]} {config.STATS[s][1]}: <b>{stats[s]}</b> "
        f"— <i>{config.STATS[s][2]}</i>"
        for s in config.STATS
    )
    text = (
        f"👤 <b>Профиль</b> {name}\n\n"
        f"🎖️ Класс: {classes.class_name(player['klass'])}\n"
        f"⭐ Уровень {level}  {_progress_bar(into, need)}  {into}/{need} XP\n\n"
        f"{stat_lines}\n\n"
        f"🪙 Монеты: {int(player['coins'])}\n"
        f"📏 Размер в этом чате: {size} см"
    )
    markup = None
    if not player["klass"]:
        text += "\n\n<b>Выбери класс</b> (влияет на распределение характеристик):"
        markup = _class_keyboard(user.id)
    return text, markup


async def _set_class(query, context, chat_key, payload):
    """Выбор класса персонажа (только владельцем профиля)."""
    owner_str, _, code = payload.partition("_")
    try:
        owner_id = int(owner_str)
    except ValueError:
        return
    if query.from_user.id != owner_id:
        await _answer(query, "Это не твой профиль!", alert=True)
        return
    if character.get_or_create(owner_id)["klass"]:
        await _answer(query, "Класс уже выбран.", alert=True)
        return
    if not character.set_class(owner_id, code):
        return
    text, markup = cmd_profile(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, owner_id))


# --- Экспедиции -------------------------------------------------------------

def _format_duration(seconds):
    h, m = seconds // 3600, (seconds % 3600) // 60
    if h and m:
        return f"{h}ч {m}м"
    return f"{h}ч" if h else f"{m}м"


def _format_left(td):
    total = max(0, int(td.total_seconds()))
    h, m = total // 3600, (total % 3600) // 60
    return f"{h}ч {m}м" if h else f"{m}м"


def cmd_expedition(chat_key, user):
    player = character.get_or_create(user.id, user.username, user.first_name)
    active = database.get_active_expedition(user.id)

    if active:
        zone = config.ZONES.get(active["zone"], {})
        head = f"{zone.get('emoji', '')} {zone.get('name', '')}"
        if expeditions.is_ready(active):
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🎁 Забрать награду", callback_data="claim_exp")]]
            )
            return (f"🗺️ <b>Экспедиция вернулась!</b>\n\n{head}\nЗабери награду 👇",
                    markup)
        left = _format_left(expeditions.time_left(active))
        return f"🗺️ <b>Герой в экспедиции</b>\n\n{head}\n⏳ Вернётся через {left}"

    text = "🗺️ <b>Выбери зону для экспедиции:</b>\n\n"
    rows = []
    for code, zone, unlocked in expeditions.available_zones(player["level"]):
        dur = _format_duration(zone["duration"])
        if unlocked:
            text += (f"{zone['emoji']} <b>{zone['name']}</b> — {dur}, "
                     f"опыт {zone['exp']}, монеты {zone['coins'][0]}–{zone['coins'][1]}\n")
            rows.append([InlineKeyboardButton(f"{zone['emoji']} {zone['name']}",
                                              callback_data=f"start_exp_{code}")])
        else:
            text += f"🔒 {zone['emoji']} {zone['name']} — нужен уровень {zone['min_level']}\n"
    return text, (InlineKeyboardMarkup(rows) if rows else None)


async def _start_expedition(query, context, chat_key, zone_code):
    user = query.from_user
    result = expeditions.start(user.id, zone_code, chat_key)
    if isinstance(result, str):
        await _answer(query, result, alert=True)
        return
    zone = config.ZONES[zone_code]
    await query.edit_message_text(
        f"🗺️ <b>Герой отправился в экспедицию!</b>\n\n"
        f"{zone['emoji']} {zone['name']}\n"
        f"⏳ Вернётся через {_format_duration(zone['duration'])}",
        parse_mode=ParseMode.HTML,
        reply_markup=_with_back(None, user.id),
    )
    _schedule_expedition_return(context, chat_key, zone["duration"])


def _item_full(instance):
    """Название предмета + его характеристики: «🟣 ⚔️ Клинок бури (💪 +11  💥 +2)»."""
    label = loot.item_label(instance["template"])
    bonus = loot.stats_text(instance.get("stats") or {})
    return f"{label} ({bonus})" if bonus else label


def _reward_text(reward):
    zone = reward["zone"]
    text = (
        f"🗺️ <b>Экспедиция завершена!</b>\n{zone['emoji']} {zone['name']}\n\n"
        f"✨ +{reward['exp']} XP\n"
        f"🪙 +{reward['coins']} монет\n"
        f"🎁 Добыча: {_item_full(reward['item'])}"
    )
    if reward["level_up"] > 0:
        text += f"\n🎉 Новый уровень: <b>{reward['level']}</b>!"
    return text


async def _claim_expedition(query, context, chat_key):
    reward = expeditions.claim(query.from_user.id)
    if reward is None:
        await _answer(query, "Награда уже забрана или экспедиция ещё идёт.",
                           alert=True)
        return
    await query.edit_message_text(_reward_text(reward), parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(None, query.from_user.id))


def _is_postable_chat(chat_key):
    """Можно ли отправить сообщение в чат (реальный chat_id активной группы)."""
    try:
        int(chat_key)
    except (TypeError, ValueError):
        return False
    return any(c["chat_id"] == str(chat_key) for c in database.get_active_chats())


def _schedule_expedition_return(context, chat_key, duration):
    if context.job_queue is None or not _is_postable_chat(chat_key):
        return
    context.job_queue.run_once(
        _expedition_return_job, duration, data={"chat_key": chat_key},
    )


async def _expedition_return_job(context: ContextTypes.DEFAULT_TYPE):
    """Проверить вернувшиеся экспедиции этого чата и объявить добычу."""
    chat_key = context.job.data["chat_key"]
    # Дайджест: собираем все готовые и ещё не забранные экспедиции этого чата
    lines = []
    for user_id in database.get_pending_expedition_users(chat_key):
        reward = expeditions.claim(user_id)
        if reward is None:
            continue
        player = database.get_or_create_player(user_id)
        name = format_mention(player["user_id"], player["username"],
                              player["first_name"])
        lines.append(f"🗺️ {name}: {_item_full(reward['item'])} "
                     f"🪙 +{reward['coins']}")
    if not lines:
        return
    text = "🎁 <b>Экспедиции вернулись!</b>\n\n" + "\n".join(lines)
    try:
        await context.bot.send_message(int(chat_key), text, parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось объявить возврат экспедиций в чат %s", chat_key)


# --- Инвентарь --------------------------------------------------------------

def _item_line(it):
    """Строка предмета с его характеристиками для инвентаря."""
    bonus = loot.stats_text(loot.item_bonus(it))
    return f"{loot.item_label(it['template'])} ({bonus})" if bonus \
        else loot.item_label(it["template"])


def cmd_inventory(chat_key, user):
    character.get_or_create(user.id, user.username, user.first_name)
    items = database.get_inventory(user.id, limit=config.INVENTORY_DISPLAY_LIMIT)
    if not items:
        return ("🎒 Инвентарь пуст.\nОтправляйся в экспедицию за добычей! 🗺️", None)

    equipped = {i["slot"]: i for i in items if i["equipped"]}
    text = "🎒 <b>Инвентарь</b>\n\n<b>Надето:</b>\n"
    for slot, (emoji, sname, _stat) in config.SLOTS.items():
        it = equipped.get(slot)
        text += f"{emoji} {sname}: {_item_line(it) if it else '—'}\n"

    text += "\n<b>Предметы:</b> (нажми, чтобы надеть)\n"
    rows = []
    # Учёт хлама для быстрой распродажи
    scrap = {}
    for it in items:
        mark = "✅ " if it["equipped"] else ""
        text += f"{mark}{_item_line(it)}\n"
        if not it["equipped"]:
            rows.append([
                InlineKeyboardButton(f"🔧 {loot.item_label(it['template'])}",
                                     callback_data=f"equip_{it['id']}"),
                InlineKeyboardButton(f"💰 {config.SELL_PRICES.get(it['rarity'], 0)}",
                                     callback_data=f"sell_{it['id']}"),
            ])
            scrap[it["rarity"]] = scrap.get(it["rarity"], 0) + 1

    # Быстрая распродажа обычных/необычных
    bulk = []
    for rarity in ("common", "uncommon"):
        if scrap.get(rarity):
            emoji = config.RARITIES[rarity][0]
            bulk.append(InlineKeyboardButton(
                f"Продать все {emoji} ({scrap[rarity]})",
                callback_data=f"sellall_{rarity}"))
    if bulk:
        rows.append(bulk)
    return text, InlineKeyboardMarkup(rows) if rows else None


async def _equip_item(query, context, chat_key, item_id):
    user = query.from_user
    # Сравнение с текущим предметом слота — для наглядного попапа
    before = character.stats_for_user(user.id)
    if not database.equip_item(user.id, item_id):
        await _answer(query, "Это не твой предмет.", alert=True)
        return
    after = character.stats_for_user(user.id)
    diff = _stat_diff_text(before, after)
    await _answer(query, f"✅ Надето! {diff}" if diff else "✅ Надето!")
    text, markup = cmd_inventory(chat_key, user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, user.id))


def _stat_diff_text(before, after):
    """Изменение характеристик после экипировки: «💪 12→20  💥 5→7»."""
    parts = []
    for stat, (emoji, _n, _d) in config.STATS.items():
        if after.get(stat, 0) != before.get(stat, 0):
            parts.append(f"{emoji} {before.get(stat, 0)}→{after.get(stat, 0)}")
    return "  ".join(parts)


async def _sell_item(query, context, chat_key, item_id):
    price = economy.sell_item(query.from_user.id, item_id)
    if price is None:
        await _answer(query, "Нельзя продать (надет или не твой).", alert=True)
        return
    await _answer(query, f"💰 Продано за {price} монет")
    text, markup = cmd_inventory(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, query.from_user.id))


async def _sell_all(query, context, chat_key, rarity):
    count, coins = economy.sell_all(query.from_user.id, rarity)
    await _answer(query, f"💰 Продано {count} шт. за {coins} монет" if count
                  else "Нечего продавать.", alert=True)
    text, markup = cmd_inventory(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, query.from_user.id))


# --- Боссы ------------------------------------------------------------------

def boss_message(active_boss, owner_id=None):
    """Карточка босса с полосой HP и кнопкой удара.

    ``owner_id`` задаётся, когда карточка живёт в чьём-то меню: тогда после
    удара сохранится кнопка «⬅️ Меню». Общая карточка в чате (авто-спавн) —
    без владельца, чтобы никто не мог «увести» её в своё меню.
    """
    hp = max(0, int(active_boss["hp"]))
    bar = _progress_bar(hp, active_boss["max_hp"])
    text = (
        f"{active_boss['emoji']} <b>{active_boss['name']}</b>\n\n"
        f"❤️ HP: {bar}  {hp}/{active_boss['max_hp']}\n\n"
        f"Бейте босса вместе! Награда — по вкладу урона."
    )
    contributors = database.get_boss_contributors(active_boss["id"])
    if contributors:
        text += "\n\n<b>Вклад урона:</b>\n"
        for c in contributors[:5]:
            p = database.get_or_create_player(c["user_id"])
            cname = format_mention(p["user_id"], p["username"], p["first_name"])
            text += f"⚔️ {cname} — {int(c['damage'])}\n"
    hit_data = f"boss_hit_{owner_id}" if owner_id else "boss_hit"
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⚔️ Ударить", callback_data=hit_data)]]
    )
    return text, markup


def cmd_boss(chat_key, user):
    active, _is_new = boss.summon(chat_key)
    return boss_message(active, owner_id=user.id)


def _boss_defeat_text(result):
    b = result["boss"]
    lines = [
        f"💥 <b>{b['emoji']} {b['name']} повержен!</b>\n",
        "🏆 <b>Награды по вкладу урона:</b>",
    ]
    for r in result["rewards"][:5]:
        player = database.get_or_create_player(r["user_id"])
        name = format_mention(player["user_id"], player["username"],
                              player["first_name"])
        crown = "👑 " if r["top"] else ""
        lines.append(f"{crown}{name}: {_item_full(r['item'])}  🪙 +{r['coins']}")
    return "\n".join(lines)


async def _boss_hit(query, context, chat_key, owner_id=None):
    result = boss.hit(query.from_user.id, chat_key)
    status = result["status"]

    if status == "no_boss":
        await _answer(query, "Босс уже повержен!", alert=True)
    elif status == "cooldown":
        mins = int(result["left"] // 60) + 1
        await _answer(query, f"Ты уже бил. Отдышись ~{mins} мин.", alert=True)
    elif status == "hit":
        crit = " 💥КРИТ!" if result.get("crit") else ""
        await _answer(query, f"⚔️ Урон: {result['damage']}{crit}")
        updated = dict(result["boss"])
        updated["hp"] = result["hp"]
        text, markup = boss_message(updated, owner_id=owner_id)
        if owner_id:
            markup = _with_back(markup, owner_id)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                      reply_markup=markup)
    elif status == "killed":
        await _answer(query, "💥 БОСС ПОВЕРЖЕН!")
        await query.edit_message_text(
            _boss_defeat_text(result), parse_mode=ParseMode.HTML,
            reply_markup=_with_back(None, owner_id) if owner_id else None)


# --- Подземелья -------------------------------------------------------------

def _dungeon_room_message(run, owner_id):
    d = dungeon.get_dungeon(run["dungeon"]) or {"emoji": "🏰", "name": "Подземелье"}
    hp = max(0, int(run["hp"]))
    bar = _progress_bar(hp, run["max_hp"])
    risk = int(dungeon.trap_chance(dungeon.get_dungeon(run["dungeon"])
               or next(iter(config.DUNGEONS.values())), run["depth"] + 1) * 100)
    text = (
        f"{d['emoji']} <b>{d['name']} — глубина {run['depth']}</b>\n\n"
        f"❤️ HP: {bar}  {hp}/{run['max_hp']}\n"
        f"🪙 Накоплено: {run['coins_earned']}  🎁 Добыча: {run['treasures']}\n"
        f"⚠️ Риск ловушки дальше: ~{risk}%\n\n"
        f"Идти глубже или уйти с добычей?"
    )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬇️ Глубже", callback_data=f"dng_deep_{owner_id}"),
        InlineKeyboardButton("🚪 Уйти с добычей", callback_data=f"dng_leave_{owner_id}"),
    ]])
    return text, markup


def cmd_dungeon(chat_key, user):
    player = character.get_or_create(user.id, user.username, user.first_name)
    run = database.get_active_dungeon_run(user.id)
    if run:
        return _dungeon_room_message(run, user.id)

    text = (
        "🏰 <b>Подземелья</b>\n\n"
        "Спускайся вглубь за монетами и добычей, но риск ловушки растёт с "
        "глубиной. Уйти с добычей можно в любой момент — или погибнуть и "
        f"потерять всё.\n\n🪙 Баланс: {int(player['coins'])} монет\n\n"
    )
    rows = []
    for code, d, unlocked in dungeon.available_dungeons(player["level"]):
        if unlocked:
            text += (f"{d['emoji']} <b>{d['name']}</b> — вход {d['entry_cost']} 🪙, "
                     f"с ур. {d['min_level']}\n")
            rows.append([InlineKeyboardButton(
                f"{d['emoji']} {d['name']} ({d['entry_cost']} 🪙)",
                callback_data=f"dng_enter_{code}")])
        else:
            text += f"🔒 {d['emoji']} {d['name']} — нужен уровень {d['min_level']}\n"
    return text, (InlineKeyboardMarkup(rows) if rows else None)


async def _dungeon_enter(query, context, chat_key, dungeon_code):
    user = query.from_user
    result = dungeon.enter(user.id, dungeon_code)
    if result["status"] == "low_level":
        await _answer(query, f"Нужен уровень {result['need']} для этого подземелья.",
                      alert=True)
        return
    if result["status"] == "no_coins":
        await _answer(query, f"Нужно {result['need']} монет (у тебя {result['have']}).",
                      alert=True)
        return
    if result["status"] not in ("entered", "in_run"):
        await _answer(query, "Не удалось войти.", alert=True)
        return
    text, markup = _dungeon_room_message(result["run"], user.id)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, user.id))


async def _dungeon_deeper(query, context, owner_id):
    user = query.from_user
    if user.id != owner_id:
        await _answer(query, "Это не твой забег!", alert=True)
        return
    result = dungeon.advance(user.id)
    status = result["status"]
    if status == "no_run":
        await _answer(query, "Забег уже завершён.", alert=True)
        return
    if status == "dead":
        await _answer(query, "💀 Ты погиб!", alert=True)
        await query.edit_message_text(
            f"💀 <b>Ты погиб на глубине {result['depth']}!</b>\n\n"
            f"Ловушка нанесла {result['damage']} урона.\n"
            f"Вся добыча и плата за вход потеряны. 🪦",
            parse_mode=ParseMode.HTML,
            reply_markup=_with_back(None, owner_id),
        )
        return
    run = database.get_active_dungeon_run(user.id)
    text, markup = _dungeon_room_message(run, owner_id)
    if status == "trap":
        await _answer(query, f"🪤 Ловушка! -{result['damage']} HP")
    elif result.get("found_item"):
        await _answer(query, f"🎁 Комната с добычей! +{result['gain']} монет")
    else:
        await _answer(query, f"🪙 Пустая комната. +{result['gain']} монет")
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, owner_id))


async def _dungeon_leave(query, context, owner_id):
    user = query.from_user
    if user.id != owner_id:
        await _answer(query, "Это не твой забег!", alert=True)
        return
    summary = dungeon.leave(user.id)
    if summary is None:
        await _answer(query, "Забег уже завершён.", alert=True)
        return
    items_text = "\n".join(_item_full(i) for i in summary["items"]) or "—"
    text = (
        f"🏰 <b>Вылазка окончена!</b>\nГлубина: {summary['depth']}\n\n"
        f"🪙 Монет: +{summary['coins']}\n"
        f"🎁 Добыча:\n{items_text}"
    )
    if summary["level_up"] > 0:
        text += f"\n\n🎉 Новый уровень: <b>{summary['level']}</b>!"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(None, owner_id))


# --- Магазин ----------------------------------------------------------------

def cmd_shop(chat_key, user):
    player = character.get_or_create(user.id, user.username, user.first_name)
    text = (
        f"🏪 <b>Магазин</b>\n\n"
        f"🪙 Баланс: <b>{int(player['coins'])}</b> монет\n\n"
        f"<b>Сундуки</b> (случайный предмет, шанс редкого выше у дорогих):\n"
    )
    rows = []
    for code, ch in config.SHOP_CHESTS.items():
        text += f"{ch['emoji']} {ch['name']} — {ch['price']} монет\n"
        rows.append([InlineKeyboardButton(
            f"{ch['emoji']} {ch['name']} ({ch['price']})",
            callback_data=f"buy_chest_{code}")])
    size = database.get_user_size(user.id, chat_key)
    text += (f"\n📏 Размер в чате: {size} см. Обмен: "
             f"{config.CM_PER_COIN} см = 1 монета.")
    conv_row = [
        InlineKeyboardButton(f"💱 {cm} см", callback_data=f"convert_{cm}")
        for cm in config.CONVERT_OPTIONS
    ]
    rows.append(conv_row)
    rows.append([
        InlineKeyboardButton("🛠️ Крафт", callback_data="craft_menu"),
        InlineKeyboardButton(f"🔄 Класс ({config.CLASS_CHANGE_COST})",
                             callback_data="shop_reclass"),
    ])
    return text, InlineKeyboardMarkup(rows)


async def _buy_chest(query, context, chat_key, chest_code):
    result = economy.buy_chest(query.from_user.id, chest_code)
    if result["status"] == "no_coins":
        await _answer(query, f"Нужно {result['need']} монет (у тебя {result['have']}).",
                           alert=True)
        return
    if result["status"] != "ok":
        return
    await _answer(query, f"🎁 Получено: {_item_full(result['item'])}", alert=True)
    text, markup = cmd_shop(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, query.from_user.id))


async def _convert_cm(query, context, chat_key, cm):
    result = economy.convert_cm(query.from_user.id, chat_key, cm)
    if result["status"] == "no_size":
        await _answer(query, f"Мало см: нужно {result['need']}, есть {result['have']}.",
                      alert=True)
        return
    if result["status"] != "ok":
        await _answer(query, "Обмен недоступен.", alert=True)
        return
    await _answer(query, f"💱 {result['cm']} см → +{result['coins']} монет", alert=True)
    text, markup = cmd_shop(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, query.from_user.id))


async def _shop_reclass(query, context, chat_key):
    user = query.from_user
    player = database.get_or_create_player(user.id)
    if player["coins"] < config.CLASS_CHANGE_COST:
        await _answer(query,
            f"Нужно {config.CLASS_CHANGE_COST} монет (у тебя {int(player['coins'])}).",
            alert=True)
        return
    rows = [
        [InlineKeyboardButton(f"{cls['emoji']} {cls['name']}",
                              callback_data=f"reclass_{user.id}_{code}")]
        for code, cls in config.CLASSES.items()
    ]
    await query.edit_message_text(
        f"🔄 <b>Смена класса</b> ({config.CLASS_CHANGE_COST} монет)\n\n"
        f"Выбери новый класс:",
        parse_mode=ParseMode.HTML,
        reply_markup=_with_back(InlineKeyboardMarkup(rows), user.id))


async def _reclass(query, context, chat_key, payload):
    owner_str, _, code = payload.partition("_")
    try:
        owner_id = int(owner_str)
    except ValueError:
        return
    if query.from_user.id != owner_id:
        await _answer(query, "Это не твой профиль!", alert=True)
        return
    result = economy.change_class(owner_id, code)
    if result["status"] == "no_coins":
        await _answer(query, f"Нужно {result['need']} монет.", alert=True)
        return
    if result["status"] != "ok":
        return
    await _answer(query, f"Класс изменён на {config.CLASSES[code]['name']}!",
                       alert=True)
    text, markup = cmd_shop(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, owner_id))


# --- Ферма (пассивный доход) ------------------------------------------------

def cmd_farm(chat_key, user):
    player = character.get_or_create(user.id, user.username, user.first_name)
    level = player["property_level"] or 0
    prop = economy.property_at(level)
    pending = economy.pending_income(player)

    text = "🏡 <b>Ферма</b> (пассивный доход)\n\n"
    if prop:
        cap = prop["rate_per_hour"] * config.PROPERTY_CAP_HOURS
        text += (f"{prop['emoji']} {prop['name']} (ур. {level}) — "
                 f"{prop['rate_per_hour']} монет/час\n"
                 f"🪙 Накоплено: <b>{pending}</b> / {cap}\n\n")
    else:
        text += "У тебя пока нет фермы — купи первую для пассивного дохода.\n\n"
    text += f"Баланс: {int(player['coins'])} монет"

    rows = []
    if prop and pending > 0:
        rows.append([InlineKeyboardButton(f"🪙 Собрать ({pending})",
                                          callback_data="claim_income")])
    nxt = economy.next_property(level)
    if nxt:
        verb = "Купить" if level == 0 else "Улучшить"
        rows.append([InlineKeyboardButton(
            f"⬆️ {verb}: {nxt['emoji']} {nxt['name']} ({nxt['upgrade_cost']})",
            callback_data="upgrade_prop")])
    return text, (InlineKeyboardMarkup(rows) if rows else None)


async def _claim_income(query, context, chat_key):
    amount = economy.claim_income(query.from_user.id)
    await _answer(query, f"🪙 Собрано: +{amount} монет" if amount
                       else "Пока нечего собирать.", alert=True)
    text, markup = cmd_farm(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, query.from_user.id))


async def _upgrade_prop(query, context, chat_key):
    result = economy.upgrade_property(query.from_user.id)
    if result["status"] == "no_coins":
        await _answer(query, f"Нужно {result['need']} монет (у тебя {result['have']}).",
                           alert=True)
        return
    if result["status"] == "max":
        await _answer(query, "Ферма уже максимального уровня!", alert=True)
        return
    await _answer(query, f"🏡 {result['property']['name']} (ур. {result['level']})!",
                       alert=True)
    text, markup = cmd_farm(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, query.from_user.id))


# --- Крафт ------------------------------------------------------------------

def cmd_craft(chat_key, user):
    uid = user.id
    character.get_or_create(uid, user.username, user.first_name)
    need = config.CRAFT_ITEMS_REQUIRED
    order = config.RARITY_ORDER
    text = (
        f"🛠️ <b>Крафт</b>\n\n"
        f"Из {need} ненадетых предметов одного тира — 1 предмет тира выше "
        f"(берутся самые старые).\n\n"
    )
    rows = []
    for i, rarity in enumerate(order[:-1]):
        cnt = database.count_items_by_rarity(uid, rarity)
        emoji, nxt = config.RARITIES[rarity][0], config.RARITIES[order[i + 1]][0]
        text += f"{emoji} → {nxt}:  {cnt}/{need}\n"
        if cnt >= need:
            rows.append([InlineKeyboardButton(
                f"Скрафтить {emoji} → {nxt}", callback_data=f"craft_{rarity}")])
    if not rows:
        text += "\nПока нечего крафтить — накопи 5 одинаковых по редкости."
    return text, (InlineKeyboardMarkup(rows) if rows else None)


async def _craft_menu(query, context, chat_key):
    text, markup = cmd_craft(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, query.from_user.id))


async def _craft(query, context, chat_key, rarity):
    result = economy.craft(query.from_user.id, rarity)
    if result["status"] == "not_enough":
        await _answer(query, f"Нужно {result['need']} шт. (есть {result['have']}).",
                      alert=True)
        return
    if result["status"] != "ok":
        await _answer(query, "Крафт недоступен.", alert=True)
        return
    await _answer(query, f"🛠️ Скрафчено: {_item_full(result['item'])}", alert=True)
    text, markup = cmd_craft(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                  reply_markup=_with_back(markup, query.from_user.id))


# --- Пояснения --------------------------------------------------------------

def cmd_info(chat_key, user):
    stats = "\n".join(f"{e} <b>{n}</b> — {d}" for e, n, d in config.STATS.values())
    rarities = "  ".join(f"{r[0]}" for r in config.RARITIES.values())
    text = (
        "ℹ️ <b>Как всё устроено</b>\n\n"
        "<b>Персонаж</b> — общий во всех чатах. Опыт капает с grow, дуэлей, "
        "экспедиций, боссов и подземелий; уровень даёт очки характеристик.\n\n"
        f"<b>Характеристики:</b>\n{stats}\n\n"
        f"<b>Редкости</b> (реже → ценнее):\n{rarities}\n"
        "Эпик+ дают вторичные статы, мифик+ — несколько.\n\n"
        "<b>Слоты:</b> "
        + ", ".join(f"{e} {n}" for e, n, _ in config.SLOTS.values()) + "\n\n"
        "<b>Дуэль:</b> шанс = 50% ± Сила (коридор "
        f"{int(config.DUEL_CHANCE_MIN*100)}–{int(config.DUEL_CHANCE_MAX*100)}%).\n"
        f"<b>Босс:</b> урон от Силы, Крит удваивает (до {int(config.BOSS_CRIT_CAP*100)}%).\n"
        f"<b>Экспедиции:</b> Скорость ускоряет (до {int(config.EXPEDITION_SPEED_CAP*100)}%).\n"
        f"<b>Подземелье:</b> Живучесть = запас HP.\n"
        f"<b>Экономика:</b> монеты с добычи; обмен {config.CM_PER_COIN} см = 1 🪙; "
        "трать в магазине, на ферму, крафт и казино."
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
    player = character.get_or_create(user.id, user.username, user.first_name)
    coins = int(player["coins"])
    if coins <= 0:
        return ("😢 Нет монет для ставки!\nЗаработай на экспедициях, боссах "
                "или обменяй см в магазине 🪙", None)

    buttons, row = [], []
    for stake in config.CASINO_STAKES:
        if stake <= coins:
            row.append(InlineKeyboardButton(f"{stake} 🪙",
                                            callback_data=f"casino_{stake}"))
        if len(row) >= 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if not buttons:
        buttons = [[InlineKeyboardButton("1 🪙", callback_data="casino_1")]]

    text = (
        f"🎰 <b>КАЗИНО</b>\n\n"
        f"🪙 Баланс: <b>{coins}</b> монет\n"
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
            f"⚠️ Твоя пипися всего {size} см.\nСтавка больше твоего размера!",
            reply_markup=_with_back(None, user.id),
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

    # Проверки — ДО атомарного клейма, чтобы не «сжигать» дуэль зря:
    # раньше при самоприёме дуэль пересоздавалась с новым id, а кнопка
    # ссылалась на старый — вызов становился мёртвым.
    duel = database.get_duel(duel_id)
    if duel is None or duel["status"] != "active":
        await _answer(query, "Дуэль уже завершена или истекла!", alert=True)
        return

    challenger_id = duel["challenger_id"]
    bet = int(duel["bet"])

    if accepter.id == challenger_id:
        await _answer(query, "Ты не можешь принять свой же вызов!", alert=True)
        return

    if database.get_user_size(accepter.id, chat_key) < bet:
        await _answer(query, "😢 Твоя пипися короче ставки! Возвращайся позже",
                      alert=True)
        return

    # Атомарный клейм: при гонке двух принявших выигрывает ровно один
    if database.claim_duel(duel_id, accepter.id) is None:
        await _answer(query, "Дуэль уже завершена или истекла!", alert=True)
        return

    _cancel_duel_timeout(context, duel_id)

    win_chance = character.duel_win_chance(challenger_id, accepter.id)
    winner_id, loser_id = database.resolve_duel(challenger_id, accepter.id, chat_key,
                                                bet, win_chance)
    database.get_or_create_user(accepter.id, chat_key, accepter.username,
                                accepter.first_name)
    character.grant_exp(winner_id, config.EXP_PER_DUEL_WIN)
    character.grant_exp(loser_id, config.EXP_PER_DUEL_LOSS)

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
        f"💀 Проигравший: {loser_name}! (-{bet} см)\n\n"
        f"✨ +{config.EXP_PER_DUEL_WIN} XP победителю, "
        f"+{config.EXP_PER_DUEL_LOSS} XP проигравшему"
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
    coins = int(database.get_or_create_player(user.id)["coins"])
    if bet > coins:
        await _answer(query, "⚠️ Ставка больше твоего баланса!", alert=True)
        return

    win = random.random() < 0.5
    new_coins = economy.play_casino(user.id, bet, win)
    if win:
        prize = bet * (config.CASINO_WIN_MULTIPLIER - 1)
        popup = f"🎉 ПОБЕДА! +{prize} 🪙 (теперь {new_coins})"
    else:
        popup = f"💀 МИМО! -{bet} 🪙 (теперь {new_coins})"
    # Результат — попапом, а панель ставок остаётся: можно крутить дальше
    # в том же сообщении, не роняя новые в чат.
    await _answer(query, popup, alert=True)
    rendered = _as_pair(cmd_casino(chat_key, user))
    text, markup = rendered
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                      reply_markup=_with_back(markup, user.id))
    except Exception:  # noqa: BLE001 — текст не изменился (тот же размер) — не страшно
        pass
