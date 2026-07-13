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

# Пункты меню inline-режима: (id, заголовок, описание)
MENU = [
    ("grow", "📈 Grow", "Увеличить пиписю"),
    ("profile", "👤 Профиль", "Персонаж, класс, уровень"),
    ("expedition", "🗺️ Экспедиция", "Отправить героя за добычей"),
    ("inventory", "🎒 Инвентарь", "Предметы и экипировка"),
    ("boss", "🐉 Босс", "Сразиться с боссом чата"),
    ("dungeon", "🏰 Подземелье", "Рискнуть в подземелье"),
    ("shop", "🏪 Магазин", "Сундуки и смена класса"),
    ("farm", "🏡 Ферма", "Пассивный доход"),
    ("top", "🏆 Top", "Топ участников"),
    ("weektop", "📅 Топ недели", "Прирост за 7 дней"),
    ("dickofday", "🎉 Dick Of Day", "Писюн дня"),
    ("stats", "📊 Stats", "Статистика"),
    ("duel", "⚔️ Duel", "Дуэль"),
    ("casino", "🎰 Casino", "Казино"),
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
        elif data == "dng_enter":
            await _dungeon_enter(query, context, chat_key)
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
        try:
            await query.answer("⚠️ Что-то пошло не так, попробуй ещё раз", show_alert=True)
        except Exception:  # noqa: BLE001
            pass


async def _run_command(query, context, chat_key, cmd):
    """Выполнить команду меню и обновить сообщение."""
    user = query.from_user
    handlers = {
        "grow": lambda: cmd_grow(chat_key, user),
        "profile": lambda: cmd_profile(chat_key, user),
        "expedition": lambda: cmd_expedition(chat_key, user),
        "inventory": lambda: cmd_inventory(chat_key, user),
        "boss": lambda: cmd_boss(chat_key, user),
        "dungeon": lambda: cmd_dungeon(chat_key, user),
        "shop": lambda: cmd_shop(chat_key, user),
        "farm": lambda: cmd_farm(chat_key, user),
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

    stat_line = "  ".join(
        f"{config.STATS[s][0]} {config.STATS[s][1]} {stats[s]}" for s in config.STATS
    )
    text = (
        f"👤 <b>Профиль</b> {name}\n\n"
        f"🎖️ Класс: {classes.class_name(player['klass'])}\n"
        f"⭐ Уровень {level}  {_progress_bar(into, need)}  {into}/{need} XP\n"
        f"{stat_line}\n"
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
        await query.answer("Это не твой профиль!", show_alert=True)
        return
    if character.get_or_create(owner_id)["klass"]:
        await query.answer("Класс уже выбран.", show_alert=True)
        return
    if not character.set_class(owner_id, code):
        return
    text, markup = cmd_profile(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


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
        await query.answer(result, show_alert=True)
        return
    zone = config.ZONES[zone_code]
    await query.edit_message_text(
        f"🗺️ <b>Герой отправился в экспедицию!</b>\n\n"
        f"{zone['emoji']} {zone['name']}\n"
        f"⏳ Вернётся через {_format_duration(zone['duration'])}",
        parse_mode=ParseMode.HTML,
    )
    _schedule_expedition_return(context, chat_key, zone["duration"])


def _reward_text(reward):
    zone = reward["zone"]
    text = (
        f"🗺️ <b>Экспедиция завершена!</b>\n{zone['emoji']} {zone['name']}\n\n"
        f"✨ +{reward['exp']} XP\n"
        f"🪙 +{reward['coins']} монет\n"
        f"🎁 Добыча: {loot.item_label(reward['item'])}"
    )
    if reward["level_up"] > 0:
        text += f"\n🎉 Новый уровень: <b>{reward['level']}</b>!"
    return text


async def _claim_expedition(query, context, chat_key):
    reward = expeditions.claim(query.from_user.id)
    if reward is None:
        await query.answer("Награда уже забрана или экспедиция ещё идёт.",
                           show_alert=True)
        return
    await query.edit_message_text(_reward_text(reward), parse_mode=ParseMode.HTML)


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
        lines.append(f"🗺️ {name}: {loot.item_label(reward['item'])} "
                     f"🪙 +{reward['coins']}")
    if not lines:
        return
    text = "🎁 <b>Экспедиции вернулись!</b>\n\n" + "\n".join(lines)
    try:
        await context.bot.send_message(int(chat_key), text, parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось объявить возврат экспедиций в чат %s", chat_key)


# --- Инвентарь --------------------------------------------------------------

def cmd_inventory(chat_key, user):
    character.get_or_create(user.id, user.username, user.first_name)
    items = database.get_inventory(user.id, limit=config.INVENTORY_DISPLAY_LIMIT)
    if not items:
        return "🎒 Инвентарь пуст.\nОтправляйся в экспедицию за добычей! 🗺️"

    equipped = {i["slot"]: i for i in items if i["equipped"]}
    text = "🎒 <b>Инвентарь</b>\n\n<b>Надето:</b>\n"
    for slot, (emoji, sname, _stat) in config.SLOTS.items():
        it = equipped.get(slot)
        shown = loot.item_label(it["template"]) if it else "—"
        text += f"{emoji} {sname}: {shown}\n"

    text += "\n<b>Предметы:</b>\n"
    rows = []
    for it in items:
        mark = "✅ " if it["equipped"] else ""
        text += f"{mark}{loot.item_label(it['template'])}\n"
        if not it["equipped"]:
            rows.append([InlineKeyboardButton(
                f"Надеть: {loot.item_label(it['template'])}",
                callback_data=f"equip_{it['id']}")])
    return text, (InlineKeyboardMarkup(rows) if rows else None)


async def _equip_item(query, context, chat_key, item_id):
    user = query.from_user
    if not database.equip_item(user.id, item_id):
        await query.answer("Это не твой предмет.", show_alert=True)
        return
    text, markup = cmd_inventory(chat_key, user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


# --- Боссы ------------------------------------------------------------------

def boss_message(active_boss):
    """Карточка босса с полосой HP и кнопкой удара."""
    hp = max(0, int(active_boss["hp"]))
    bar = _progress_bar(hp, active_boss["max_hp"])
    text = (
        f"{active_boss['emoji']} <b>{active_boss['name']}</b>\n\n"
        f"❤️ HP: {bar}  {hp}/{active_boss['max_hp']}\n\n"
        f"Бейте босса вместе! Награда — по вкладу урона."
    )
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⚔️ Ударить", callback_data="boss_hit")]]
    )
    return text, markup


def cmd_boss(chat_key, user):
    active, _is_new = boss.summon(chat_key)
    return boss_message(active)


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
        lines.append(f"{crown}{name}: {loot.item_label(r['item'])}  🪙 +{r['coins']}")
    return "\n".join(lines)


async def _boss_hit(query, context, chat_key):
    result = boss.hit(query.from_user.id, chat_key)
    status = result["status"]

    if status == "no_boss":
        await query.answer("Босс уже повержен!", show_alert=True)
    elif status == "cooldown":
        mins = int(result["left"] // 60) + 1
        await query.answer(f"Ты уже бил. Отдышись ~{mins} мин.", show_alert=True)
    elif status == "hit":
        await query.answer(f"⚔️ Урон: {result['damage']}")
        updated = dict(result["boss"])
        updated["hp"] = result["hp"]
        text, markup = boss_message(updated)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                      reply_markup=markup)
    elif status == "killed":
        await query.answer("💥 БОСС ПОВЕРЖЕН!")
        await query.edit_message_text(_boss_defeat_text(result),
                                      parse_mode=ParseMode.HTML)


# --- Подземелья -------------------------------------------------------------

def _dungeon_room_message(run, owner_id):
    hp = max(0, int(run["hp"]))
    bar = _progress_bar(hp, run["max_hp"])
    text = (
        f"🏰 <b>Подземелье — глубина {run['depth']}</b>\n\n"
        f"❤️ HP: {bar}  {hp}/{run['max_hp']}\n"
        f"🪙 Накоплено: {run['coins_earned']}  📦 Сундуков: {run['treasures']}\n\n"
        f"Идти глубже или уйти с добычей?"
    )
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬇️ Глубже", callback_data=f"dng_deep_{owner_id}"),
        InlineKeyboardButton("🚪 Уйти с добычей", callback_data=f"dng_leave_{owner_id}"),
    ]])
    return text, markup


def cmd_dungeon(chat_key, user):
    character.get_or_create(user.id, user.username, user.first_name)
    run = database.get_active_dungeon_run(user.id)
    if run:
        return _dungeon_room_message(run, user.id)

    player = database.get_or_create_player(user.id)
    cost = config.DUNGEON_ENTRY_COST
    text = (
        f"🏰 <b>Подземелье</b>\n\n"
        f"Спускайся вглубь за сокровищами, но берегись ловушек!\n"
        f"Уйти с добычей можно в любой момент — или потерять всё.\n\n"
        f"💰 Вход: {cost} монет (у тебя {int(player['coins'])})"
    )
    if player["coins"] >= cost:
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"🏰 Войти ({cost} монет)",
                                   callback_data="dng_enter")]]
        )
    else:
        text += "\n\n😔 Не хватает монет — сходи в экспедицию или победи босса."
        markup = None
    return text, markup


async def _dungeon_enter(query, context, chat_key):
    user = query.from_user
    result = dungeon.enter(user.id)
    if result["status"] == "no_coins":
        await query.answer(
            f"Нужно {result['need']} монет (у тебя {result['have']}).",
            show_alert=True,
        )
        return
    text, markup = _dungeon_room_message(result["run"], user.id)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _dungeon_deeper(query, context, owner_id):
    user = query.from_user
    if user.id != owner_id:
        await query.answer("Это не твой забег!", show_alert=True)
        return
    result = dungeon.advance(user.id)
    status = result["status"]
    if status == "no_run":
        await query.answer("Забег уже завершён.", show_alert=True)
        return
    if status == "dead":
        await query.answer("💀 Ты погиб!", show_alert=True)
        await query.edit_message_text(
            f"💀 <b>Ты погиб на глубине {result['depth']}!</b>\n\n"
            f"Ловушка нанесла {result['damage']} урона.\n"
            f"Вся добыча и плата за вход потеряны. 🪦",
            parse_mode=ParseMode.HTML,
        )
        return
    run = database.get_active_dungeon_run(user.id)
    text, markup = _dungeon_room_message(run, owner_id)
    if status == "trap":
        await query.answer(f"🪤 Ловушка! -{result['damage']} HP")
    else:
        await query.answer(f"📦 Сундук! +{result['gain']} монет")
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _dungeon_leave(query, context, owner_id):
    user = query.from_user
    if user.id != owner_id:
        await query.answer("Это не твой забег!", show_alert=True)
        return
    summary = dungeon.leave(user.id)
    if summary is None:
        await query.answer("Забег уже завершён.", show_alert=True)
        return
    items_text = "\n".join(loot.item_label(i) for i in summary["items"]) or "—"
    text = (
        f"🏰 <b>Вылазка окончена!</b>\nГлубина: {summary['depth']}\n\n"
        f"🪙 Монет: +{summary['coins']}\n"
        f"🎁 Добыча:\n{items_text}"
    )
    if summary["level_up"] > 0:
        text += f"\n\n🎉 Новый уровень: <b>{summary['level']}</b>!"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)


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
    rows.append([InlineKeyboardButton(
        f"🔄 Сменить класс ({config.CLASS_CHANGE_COST})",
        callback_data="shop_reclass")])
    return text, InlineKeyboardMarkup(rows)


async def _buy_chest(query, context, chat_key, chest_code):
    result = economy.buy_chest(query.from_user.id, chest_code)
    if result["status"] == "no_coins":
        await query.answer(f"Нужно {result['need']} монет (у тебя {result['have']}).",
                           show_alert=True)
        return
    if result["status"] != "ok":
        return
    await query.answer(f"🎁 Получено: {loot.item_label(result['item'])}",
                       show_alert=True)
    text, markup = cmd_shop(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _shop_reclass(query, context, chat_key):
    user = query.from_user
    player = database.get_or_create_player(user.id)
    if player["coins"] < config.CLASS_CHANGE_COST:
        await query.answer(
            f"Нужно {config.CLASS_CHANGE_COST} монет (у тебя {int(player['coins'])}).",
            show_alert=True)
        return
    rows = [
        [InlineKeyboardButton(f"{cls['emoji']} {cls['name']}",
                              callback_data=f"reclass_{user.id}_{code}")]
        for code, cls in config.CLASSES.items()
    ]
    await query.edit_message_text(
        f"🔄 <b>Смена класса</b> ({config.CLASS_CHANGE_COST} монет)\n\n"
        f"Выбери новый класс:",
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))


async def _reclass(query, context, chat_key, payload):
    owner_str, _, code = payload.partition("_")
    try:
        owner_id = int(owner_str)
    except ValueError:
        return
    if query.from_user.id != owner_id:
        await query.answer("Это не твой профиль!", show_alert=True)
        return
    result = economy.change_class(owner_id, code)
    if result["status"] == "no_coins":
        await query.answer(f"Нужно {result['need']} монет.", show_alert=True)
        return
    if result["status"] != "ok":
        return
    await query.answer(f"Класс изменён на {config.CLASSES[code]['name']}!",
                       show_alert=True)
    text, markup = cmd_shop(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


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
    await query.answer(f"🪙 Собрано: +{amount} монет" if amount
                       else "Пока нечего собирать.", show_alert=True)
    text, markup = cmd_farm(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _upgrade_prop(query, context, chat_key):
    result = economy.upgrade_property(query.from_user.id)
    if result["status"] == "no_coins":
        await query.answer(f"Нужно {result['need']} монет (у тебя {result['have']}).",
                           show_alert=True)
        return
    if result["status"] == "max":
        await query.answer("Ферма уже максимального уровня!", show_alert=True)
        return
    await query.answer(f"🏡 {result['property']['name']} (ур. {result['level']})!",
                       show_alert=True)
    text, markup = cmd_farm(chat_key, query.from_user)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


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
