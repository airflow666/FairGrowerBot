import random
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
import database
import config

# Храним chat_id для каждого пользователя
_user_chat_ids = {}


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показываем 5 кнопок-команд"""
    results = []

    for cmd_id, title, desc in [
        ('grow', '📈 Grow', 'Увеличить пиписю'),
        ('top', '🏆 Top', 'Топ участников'),
        ('dickofday', '🎉 Dick Of Day', 'Писюн дня'),
        ('stats', '📊 Stats', 'Статистика'),
        ('duel', '⚔️ Duel', 'Дуэль'),
    ]:
        keyboard = [[InlineKeyboardButton(f"Нажми чтобы {title.lower()}", callback_data=f"cmd_{cmd_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        results.append(
            InlineQueryResultArticle(
                id=cmd_id,
                title=title,
                description=desc,
                input_message_content=InputTextMessageContent(
                    f"{title}\nНажми кнопку ниже 👇",
                    parse_mode=ParseMode.HTML
                ),
                reply_markup=reply_markup,
                thumbnail_url='https://img.icons8.com/emoji/48/000000/eggplant-emoji.png'
            )
        )

    await update.inline_query.answer(results)


async def chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем РЕАЛЬНЫЙ chat_id группы и выполняем команду"""
    chosen = update.chosen_inline_result
    result_id = chosen.result_id
    chat_id = chosen.chat_id
    user = chosen.from_user
    user_id = user.id
    username = user.username
    first_name = user.first_name

    print(f"[DEBUG] chosen: result_id={result_id}, chat_id={chat_id}, user_id={user_id}")

    if chat_id is None:
        print(f"[DEBUG] chat_id is None!")
        return

    # Сохраняем chat_id для пользователя
    _user_chat_ids[user_id] = chat_id

    # Выполняем команду и отправляем в чат
    if result_id == 'grow':
        text = await cmd_grow(chat_id, user_id, username, first_name, context)
    elif result_id == 'top':
        text = await cmd_top(chat_id, context)
    elif result_id == 'dickofday':
        text = await cmd_dickofday(chat_id, context)
    elif result_id == 'stats':
        text = await cmd_stats(chat_id, user_id, context)
    elif result_id == 'duel':
        text = await cmd_duel(chat_id, user_id, context)
        if isinstance(text, tuple):
            text, _ = text
    else:
        return

    print(f"[DEBUG] Sending to chat {chat_id}: {text[:50]}...")

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML
        )
        print(f"[DEBUG] Sent successfully!")
    except Exception as e:
        print(f"[ERROR] Failed to send: {e}")


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок — выполняет команду"""
    query = update.callback_query
    print(f"[DEBUG] Button pressed: {query.data}")
    await query.answer()

    message = query.message
    chat_instance = query.chat_instance
    user = query.from_user
    user_id = user.id

    # chat_id: из сообщения > из выбранного результата > из chat_instance
    if message and message.chat:
        chat_id = message.chat.id
        _user_chat_ids[user_id] = chat_id
        print(f"[DEBUG] Using message.chat.id: {chat_id}")
    elif user_id in _user_chat_ids:
        chat_id = _user_chat_ids[user_id]
        print(f"[DEBUG] Using saved chat_id: {chat_id}")
    elif chat_instance:
        chat_id = chat_instance
        print(f"[DEBUG] Using chat_instance: {chat_id}")
    else:
        await query.answer("⚠️ Не удалось определить чат!", show_alert=True)
        return

    username = user.username
    first_name = user.first_name
    callback_data = query.data
    print(f"[DEBUG] Processing: {callback_data}")
    
    if callback_data.startswith('cmd_'):
        cmd = callback_data.replace('cmd_', '')
        reply_markup = None
        
        if cmd == 'grow':
            text = await cmd_grow(chat_id, user_id, username, first_name, context)
        elif cmd == 'top':
            text = await cmd_top(chat_id, context)
        elif cmd == 'dickofday':
            text = await cmd_dickofday(chat_id, context)
        elif cmd == 'stats':
            text = await cmd_stats(chat_id, user_id, context)
        elif cmd == 'duel':
            result = await cmd_duel(chat_id, user_id, context)
            if isinstance(result, tuple):
                text, reply_markup = result
            else:
                text = result
        else:
            return

        try:
            if message:
                await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            else:
                inline_msg_id = query.inline_message_id
                if inline_msg_id:
                    await context.bot.edit_message_text(
                        inline_message_id=inline_msg_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup
                    )
                else:
                    await query.answer("⚠️ Сначала отправь результат в чат!", show_alert=True)
        except Exception as e:
            print(f"[ERROR] Failed: {e}")
            import traceback
            traceback.print_exc()
            await query.answer(f"Ошибка: {e}", show_alert=True)

    elif callback_data.startswith('create_duel_'):
        await create_duel(query, chat_id, callback_data, context)

    elif callback_data.startswith('accept_duel_'):
        await accept_duel(query, chat_id, callback_data, context)


async def cmd_grow(chat_id, user_id, username, first_name, context):
    database.get_or_create_user(user_id, chat_id, username, first_name)

    if not database.can_grow(user_id, chat_id):
        return (
            f"📈 Ты уже увеличивал сегодня, {first_name}!\n"
            f"Приходи после 00:00 по МСК 🕛"
        )

    change = random.randint(config.GROW_MIN, config.GROW_MAX)
    new_size = database.update_user_size(user_id, chat_id, change)
    database.update_last_grow(user_id, chat_id)

    if change > 0:
        text = f"📈 Твоя пипися выросла на <b>+{change} см</b>!"
    elif change < 0:
        text = f"📉 Твоя пипися уменьшилась на <b>{change} см</b>!"
    else:
        text = "➡️ Твоя пипися осталась без изменений!"

    text += f"\n📏 Текущий размер: <b>{new_size} см</b>"
    return text


async def cmd_top(chat_id, context):
    top_users = database.get_chat_top(chat_id, limit=10)

    if not top_users:
        return (
            "🏆 Пока никто не увеличивал свою пиписю!\n"
            "Используй Grow первым 🍆"
        )

    msg = "🏆 <b>ТОП самых огромных писюнов:</b>\n\n"
    for i, u in enumerate(top_users, 1):
        uid = u["user_id"]
        uu = u["username"]
        uf = u["first_name"]
        size = u["size"]

        if uu:
            name = f"@{uu}"
        elif uf:
            name = f'<a href="tg://user?id={uid}">{uf}</a>'
        else:
            name = f"User{uid}"

        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        msg += f"{medal} {name}: {size} см\n"

    return msg


async def cmd_dickofday(chat_id, context):
    # Сначала проверяем, есть ли уже писюн дня сегодня
    current = database.get_current_dick_of_day(chat_id)
    
    if current:
        # Писюн уже выбран — показываем его
        uid = current["user_id"]
        uu = current["username"]
        uf = current["first_name"]
        bonus = current["bonus"]
        old_size = current["old_size"]
        new_size = current["new_size"]

        if uu:
            name = f"@{uu}"
        elif uf:
            name = f'<a href="tg://user?id={uid}">{uf}</a>'
        else:
            name = f"User{uid}"

        return (
            f"🎉 <b>Писюн дня уже выбран!</b>\n\n"
            f"🏆 {name}\n"
            f"🎁 Бонус: <b>+{bonus} см</b>\n"
            f"📏 Размер: <b>{old_size} → {new_size} см</b>"
        )

    # Выбираем нового писюна дня
    result_data = database.set_dick_of_day(chat_id)

    if not result_data:
        return (
            "😔 Нет участников, чтобы выбрать писюна дня!\n"
            "Используй Grow первым 🍆"
        )

    uid = result_data["user_id"]
    uu = result_data["username"]
    uf = result_data["first_name"]

    if uu:
        name = f"@{uu}"
    elif uf:
        name = f'<a href="tg://user?id={uid}">{uf}</a>'
    else:
        name = f"User{uid}"

    return (
        f"🎉 <b>Писюн дня:</b> {name}!\n"
        f"🎁 Бонус: <b>+{result_data['bonus']} см</b>\n"
        f"📏 Новый размер: <b>{result_data['new_size']} см</b>"
    )


async def cmd_stats(chat_id, user_id, context):
    stats_data = database.get_duel_stats(user_id, chat_id)

    return (
        f"📊 <b>Статистика дуэлей:</b>\n\n"
        f"✅ Побед: {stats_data['wins']}\n"
        f"❌ Поражений: {stats_data['losses']}\n"
        f"📈 Суммарно выиграно: <b>{stats_data['total_won']} см</b>"
    )


async def cmd_duel(chat_id, user_id, context):
    current_size = database.get_user_size(user_id, chat_id)

    if current_size <= 0:
        return (
            f"😢 Твоя пипися слишком короткая!\n"
            f"Возвращайся позже 🍆"
        )

    # Кнопки с ставками
    buttons = []
    row = []
    for stake in [1, 2, 3, 4, 5]:
        if stake <= current_size:
            row.append(InlineKeyboardButton(f"{stake} см", callback_data=f"create_duel_{int(stake)}"))
        if len(row) >= 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if not buttons:
        buttons = [[InlineKeyboardButton("1 см", callback_data="create_duel_1")]]

    keyboard = buttons
    reply_markup = InlineKeyboardMarkup(keyboard)

    return (
        f"⚔️ <b>ДУЭЛЬ</b>\n\n"
        f"💰 Твой размер: <b>{current_size} см</b>\n\n"
        f"Выбери ставку:",
        reply_markup
    )


async def create_duel(query, chat_id, callback_data, context):
    """Создать дуэль"""
    parts = callback_data.split("_")
    if len(parts) < 3:
        await query.edit_message_text("❌ Ошибка!")
        return

    bet = int(parts[2])
    user_id = query.from_user.id
    user = query.from_user
    username = user.username
    first_name = user.first_name

    current_size = database.get_user_size(user_id, chat_id)

    if bet > current_size:
        await query.edit_message_text(
            f"⚠️ Твоя пипися всего {current_size} см.\n"
            f"Ставка больше твоего размера!"
        )
        return

    if username:
        challenger_name = f"@{username}"
    elif first_name:
        challenger_name = f'<a href="tg://user?id={user_id}">{first_name}</a>'
    else:
        challenger_name = f"User{user_id}"

    keyboard = [[InlineKeyboardButton("⚔️ Принять вызов!", callback_data=f"accept_duel_{user_id}_{bet}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (
        f"⚔️ <b>ДУЭЛЬ!</b>\n\n"
        f"{challenger_name} вызывает кого-нибудь на дуэль!\n"
        f"💰 Ставка: <b>{bet} см</b>\n\n"
        f"Нажми кнопку, чтобы принять вызов!"
    )

    database.create_duel(user_id, chat_id, bet, query.message.message_id if query.message else 0)

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def accept_duel(query, chat_id, callback_data, context):
    """Обработать принятие дуэли"""
    parts = callback_data.split("_")
    if len(parts) < 4:
        await query.edit_message_text("❌ Ошибка дуэли!")
        return

    challenger_id = int(parts[2])
    bet = float(parts[3])
    accepter_id = query.from_user.id

    if accepter_id == challenger_id:
        await query.answer("Ты не можешь принять свой же вызов!", show_alert=True)
        return

    # Проверить что у участника достаточно размера
    accepter_size = database.get_user_size(accepter_id, chat_id)
    if accepter_size < bet:
        await query.answer(
            f"😢 Твоя пипися слишком короткая! Возвращайся позже",
            show_alert=True
        )
        return

    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM active_duels WHERE challenger_id = ? AND chat_id = ? ORDER BY created_at DESC LIMIT 1",
        (challenger_id, chat_id)
    )
    duel = cursor.fetchone()
    conn.close()

    if not duel:
        await query.edit_message_text("❌ Дуэль уже завершена!")
        return

    duel = dict(duel)
    challenger_name = database.get_user_mention(challenger_id, chat_id)

    accepter = query.from_user
    if accepter.username:
        accepter_name = f"@{accepter.username}"
    elif accepter.first_name:
        accepter_name = f'<a href="tg://user?id={accepter_id}">{accepter.first_name}</a>'
    else:
        accepter_name = f"User{accepter_id}"

    winner_id = random.choice([challenger_id, accepter_id])
    loser_id = challenger_id if winner_id == accepter_id else accepter_id
    winner_name = challenger_name if winner_id == challenger_id else accepter_name
    loser_name = accepter_name if winner_id == challenger_id else challenger_name

    database.update_user_size(winner_id, chat_id, bet)
    database.update_user_size(loser_id, chat_id, -bet)
    database.update_duel_stats(winner_id, loser_id, chat_id, bet)

    result_text = (
        f"⚔️ <b>РЕЗУЛЬТАТ ДУЭЛИ!</b>\n\n"
        f"{challenger_name} VS {accepter_name}\n"
        f"💰 Ставка: {bet} см\n\n"
        f"🏆 Победитель: {winner_name}! (+{bet} см)\n"
        f"💀 Проигравший: {loser_name}! (-{bet} см)"
    )

    await query.edit_message_text(result_text, parse_mode=ParseMode.HTML)
