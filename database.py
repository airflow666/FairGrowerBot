import sqlite3
from datetime import datetime, timezone, timedelta
import config

# Путь к файлу базы данных
DATABASE_PATH = "fairdick.db"


def get_connection():
    """Получить соединение с базой данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # Возвращать строки как словари
    return conn


def init_db():
    """Инициализировать базу данных и создать таблицы"""
    conn = get_connection()
    cursor = conn.cursor()

    # Таблица пользователей в чатах
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sizes (
            user_id INTEGER,
            chat_id INTEGER,
            size REAL DEFAULT 0,
            last_grow TIMESTAMP,
            last_dick_of_day TIMESTAMP,
            username TEXT,
            first_name TEXT,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    # Таблица писюна дня
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dick_of_day (
            chat_id INTEGER,
            user_id INTEGER,
            bonus INTEGER,
            old_size REAL,
            new_size REAL,
            chosen_at TIMESTAMP,
            username TEXT,
            first_name TEXT,
            PRIMARY KEY (chat_id)
        )
    """)

    # Таблица статистики дуэлей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS duel_stats (
            user_id INTEGER,
            chat_id INTEGER,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            total_won REAL DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    # Таблица активных дуэлей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_duels (
            duel_id INTEGER PRIMARY KEY AUTOINCREMENT,
            challenger_id INTEGER,
            chat_id INTEGER,
            bet REAL,
            message_id INTEGER,
            created_at TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def get_or_create_user(user_id, chat_id, username=None, first_name=None):
    """Получить или создать запись пользователя в чате"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM user_sizes WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id)
    )
    user = cursor.fetchone()

    if not user:
        cursor.execute(
            """INSERT INTO user_sizes (user_id, chat_id, username, first_name, last_grow, last_dick_of_day)
               VALUES (?, ?, ?, ?, NULL, NULL)""",
            (user_id, chat_id, username, first_name)
        )
        conn.commit()
        cursor.execute(
            "SELECT * FROM user_sizes WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id)
        )
        user = cursor.fetchone()

    conn.close()
    return dict(user) if user else None


def update_user_size(user_id, chat_id, size_change):
    """Обновить размер пользователя"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE user_sizes SET size = size + ? WHERE user_id = ? AND chat_id = ?",
        (size_change, user_id, chat_id)
    )
    conn.commit()
    conn.close()

    # Вернуть новое значение
    return get_user_size(user_id, chat_id)


def get_user_size(user_id, chat_id):
    """Получить текущий размер пользователя"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT size FROM user_sizes WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id)
    )
    result = cursor.fetchone()
    conn.close()

    return result["size"] if result else 0


def can_grow(user_id, chat_id):
    """Проверить, может ли пользователь увеличить размер (раз в сутки после 00:00 МСК)"""
    user = get_or_create_user(user_id, chat_id)
    
    if not user or not user["last_grow"]:
        return True

    # Получить текущее время в МСК
    msk_now = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=3))
    )
    msk_midnight = msk_now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Если last_grow раньше сегодняшней полуночи МСК - можно
    last_grow = datetime.fromisoformat(user["last_grow"])
    if last_grow.tzinfo is None:
        last_grow = last_grow.replace(tzinfo=timezone.utc)
    last_grow_msk = last_grow.astimezone(timezone(timedelta(hours=3)))

    return last_grow_msk < msk_midnight


def update_last_grow(user_id, chat_id):
    """Обновить время последнего grow"""
    conn = get_connection()
    cursor = conn.cursor()

    msk_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3)))
    
    cursor.execute(
        "UPDATE user_sizes SET last_grow = ? WHERE user_id = ? AND chat_id = ?",
        (msk_now.isoformat(), user_id, chat_id)
    )
    conn.commit()
    conn.close()


def get_user_display_name(user_id, chat_id):
    """Получить отображаемое имя пользователя с @username или ссылкой"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT username, first_name FROM user_sizes WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id)
    )
    result = cursor.fetchone()
    conn.close()

    if not result:
        return f"User{user_id}"

    username = result["username"]
    first_name = result["first_name"]

    if username:
        return f"@{username}"
    elif first_name:
        return f"[{first_name}](tg://user?id={user_id})"
    else:
        return f"User{user_id}"


def get_user_mention(user_id, chat_id):
    """Получить упоминание пользователя: @username или имя с ссылкой"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT username, first_name FROM user_sizes WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id)
    )
    result = cursor.fetchone()
    conn.close()

    if not result:
        return f"User{user_id}"

    username = result["username"]
    first_name = result["first_name"]

    if username:
        return f"@{username}"
    elif first_name:
        return f'<a href="tg://user?id={user_id}">{first_name}</a>'
    else:
        return f"User{user_id}"


def get_chat_top(chat_id, limit=10):
    """Получить топ участников чата"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """SELECT * FROM user_sizes 
           WHERE chat_id = ? AND (last_grow IS NOT NULL OR size != 0)
           ORDER BY size DESC 
           LIMIT ?""",
        (chat_id, limit)
    )
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def get_chat_participants(chat_id):
    """Получить всех участников чата, кто хоть раз участвовал"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """SELECT * FROM user_sizes 
           WHERE chat_id = ? AND (last_grow IS NOT NULL OR size != 0)""",
        (chat_id,)
    )
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def can_dick_of_day(chat_id):
    """Проверить, можно ли выбрать писюна дня (раз в сутки)"""
    conn = get_connection()
    cursor = conn.cursor()

    msk_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3)))
    msk_midnight = msk_now.replace(hour=0, minute=0, second=0, microsecond=0)

    cursor.execute(
        "SELECT MAX(last_dick_of_day) as last_dotd FROM user_sizes WHERE chat_id = ?",
        (chat_id,)
    )
    result = cursor.fetchone()
    conn.close()

    if not result or not result["last_dotd"]:
        return True

    last_dotd = datetime.fromisoformat(result["last_dotd"])
    if last_dotd.tzinfo is None:
        last_dotd = last_dotd.replace(tzinfo=timezone.utc)
    last_dotd_msk = last_dotd.astimezone(timezone(timedelta(hours=3)))

    return last_dotd_msk < msk_midnight


def get_current_dick_of_day(chat_id):
    """Получить текущего писюна дня (если уже выбран сегодня)"""
    conn = get_connection()
    cursor = conn.cursor()

    msk_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3)))
    msk_midnight = msk_now.replace(hour=0, minute=0, second=0, microsecond=0)

    cursor.execute(
        "SELECT * FROM dick_of_day WHERE chat_id = ?",
        (chat_id,)
    )
    result = cursor.fetchone()
    conn.close()

    if not result:
        return None

    result = dict(result)
    chosen_at = datetime.fromisoformat(result["chosen_at"])
    if chosen_at.tzinfo is None:
        chosen_at = chosen_at.replace(tzinfo=timezone.utc)
    chosen_at_msk = chosen_at.astimezone(timezone(timedelta(hours=3)))

    # Если выбран сегодня
    if chosen_at_msk >= msk_midnight:
        return result
    return None


def set_dick_of_day(chat_id):
    """Выбрать случайного участника и добавить ему бонус"""
    import random

    participants = get_chat_participants(chat_id)
    if not participants:
        return None

    # Выбрать случайного участника
    winner = random.choice(participants)
    bonus = random.randint(config.DICK_OF_DAY_MIN, config.DICK_OF_DAY_MAX)

    # Обновить размер
    conn = get_connection()
    cursor = conn.cursor()

    msk_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3)))
    old_size = winner["size"]

    cursor.execute(
        "UPDATE user_sizes SET size = size + ?, last_dick_of_day = ? WHERE user_id = ? AND chat_id = ?",
        (bonus, msk_now.isoformat(), winner["user_id"], chat_id)
    )

    # Сохранить результат в таблицу dick_of_day
    cursor.execute(
        """INSERT OR REPLACE INTO dick_of_day 
           (chat_id, user_id, bonus, old_size, new_size, chosen_at, username, first_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (chat_id, winner["user_id"], bonus, old_size, old_size + bonus,
         msk_now.isoformat(), winner["username"], winner["first_name"])
    )

    conn.commit()
    conn.close()

    return {
        "user_id": winner["user_id"],
        "username": winner["username"],
        "first_name": winner["first_name"],
        "bonus": bonus,
        "old_size": old_size,
        "new_size": old_size + bonus
    }


def get_duel_stats(user_id, chat_id):
    """Получить статистику дуэлей пользователя"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM duel_stats WHERE user_id = ? AND chat_id = ?",
        (user_id, chat_id)
    )
    result = cursor.fetchone()
    conn.close()

    if not result:
        return {"wins": 0, "losses": 0, "total_won": 0}

    return dict(result)


def update_duel_stats(winner_id, loser_id, chat_id, bet):
    """Обновить статистику дуэлей после завершения"""
    conn = get_connection()
    cursor = conn.cursor()

    # Инициализировать записи если нет
    cursor.execute(
        """INSERT OR IGNORE INTO duel_stats (user_id, chat_id, wins, losses, total_won)
           VALUES (?, ?, 0, 0, 0)""",
        (winner_id, chat_id)
    )
    cursor.execute(
        """INSERT OR IGNORE INTO duel_stats (user_id, chat_id, wins, losses, total_won)
           VALUES (?, ?, 0, 0, 0)""",
        (loser_id, chat_id)
    )

    # Обновить победителя
    cursor.execute(
        "UPDATE duel_stats SET wins = wins + 1, total_won = total_won + ? WHERE user_id = ? AND chat_id = ?",
        (bet, winner_id, chat_id)
    )

    # Обновить проигравшего
    cursor.execute(
        "UPDATE duel_stats SET losses = losses + 1, total_won = total_won - ? WHERE user_id = ? AND chat_id = ?",
        (bet, loser_id, chat_id)
    )

    conn.commit()
    conn.close()


def create_duel(challenger_id, chat_id, bet, message_id):
    """Создать запись о дуэли"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """INSERT INTO active_duels (challenger_id, chat_id, bet, message_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (challenger_id, chat_id, bet, message_id, datetime.now(timezone.utc).isoformat())
    )
    duel_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return duel_id


def get_duel_by_message(message_id, chat_id):
    """Получить дуэль по ID сообщения"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM active_duels WHERE message_id = ? AND chat_id = ?",
        (message_id, chat_id)
    )
    result = cursor.fetchone()
    conn.close()

    return dict(result) if result else None


def delete_duel(duel_id):
    """Удалить запись о дуэли"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM active_duels WHERE duel_id = ?", (duel_id,))
    conn.commit()
    conn.close()
