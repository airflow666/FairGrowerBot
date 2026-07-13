"""Слой доступа к данным (SQLite).

Ключ разделения чатов (``chat_key``) — это либо реальный ``chat.id`` (когда бот
состоит в группе), либо ``chat_instance`` из callback-запроса для inline-режима.
Хранится как есть; для кода это просто непрозрачный идентификатор чата.
"""
import random
import sqlite3
from contextlib import contextmanager

import config
import utils

DATABASE_PATH = config.DATABASE_PATH


@contextmanager
def _connect():
    """Соединение с БД с автоматическим commit/close."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn, table, column, decl):
    """Добавить колонку, если её ещё нет (лёгкая миграция существующих БД)."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_db():
    """Создать таблицы и выполнить миграции."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sizes (
                user_id INTEGER,
                chat_id TEXT,
                size INTEGER DEFAULT 0,
                max_size INTEGER DEFAULT 0,
                grow_streak INTEGER DEFAULT 0,
                last_grow TIMESTAMP,
                last_grow_date TEXT,
                last_dick_of_day TIMESTAMP,
                username TEXT,
                first_name TEXT,
                PRIMARY KEY (user_id, chat_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS dick_of_day (
                chat_id TEXT PRIMARY KEY,
                user_id INTEGER,
                bonus INTEGER,
                old_size INTEGER,
                new_size INTEGER,
                chosen_date TEXT,
                chosen_at TIMESTAMP,
                username TEXT,
                first_name TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS duel_stats (
                user_id INTEGER,
                chat_id TEXT,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_won INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, chat_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS active_duels (
                duel_id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenger_id INTEGER,
                chat_id TEXT,
                bet INTEGER,
                status TEXT DEFAULT 'active',
                inline_message_id TEXT,
                created_at TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS grow_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id TEXT,
                change INTEGER,
                created_at TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER,
                chat_id TEXT,
                code TEXT,
                unlocked_at TIMESTAMP,
                PRIMARY KEY (user_id, chat_id, code)
            )
        """)

        # Чаты, куда добавлен бот (для проактивных постов и авто-событий)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id TEXT PRIMARY KEY,
                title TEXT,
                is_active INTEGER DEFAULT 1,
                added_at TIMESTAMP
            )
        """)

        # Связь inline-идентификатора чата (chat_instance) с реальным chat_id
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_links (
                chat_instance TEXT PRIMARY KEY,
                chat_id TEXT,
                linked_at TIMESTAMP
            )
        """)

        # Глобальный RPG-персонаж (один на аккаунт, ключ — user_id)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                exp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                klass TEXT,
                coins INTEGER DEFAULT 0,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMP
            )
        """)

        # Экспедиции (глобальные, ключ — user_id; одна активная за раз)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expeditions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                zone TEXT,
                chat_key TEXT,
                started_at TIMESTAMP,
                ends_at TIMESTAMP,
                status TEXT DEFAULT 'active'
            )
        """)

        # Предметы игроков (глобальные, ключ — user_id)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS player_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                template TEXT,
                rarity TEXT,
                slot TEXT,
                equipped INTEGER DEFAULT 0,
                obtained_at TIMESTAMP
            )
        """)

        # Боссы чата (общий HP-пул на чат)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bosses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_key TEXT,
                name TEXT,
                emoji TEXT,
                max_hp INTEGER,
                hp INTEGER,
                status TEXT DEFAULT 'active',
                spawned_at TIMESTAMP,
                defeated_at TIMESTAMP
            )
        """)

        # Вклад игроков в бой с боссом (урон, кулдаун)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS boss_hits (
                boss_id INTEGER,
                user_id INTEGER,
                damage INTEGER DEFAULT 0,
                hits INTEGER DEFAULT 0,
                last_hit_at TIMESTAMP,
                PRIMARY KEY (boss_id, user_id)
            )
        """)

        # Миграции для БД, созданных прежними версиями бота
        _ensure_column(conn, "user_sizes", "max_size", "INTEGER DEFAULT 0")
        _ensure_column(conn, "user_sizes", "grow_streak", "INTEGER DEFAULT 0")
        _ensure_column(conn, "user_sizes", "last_grow_date", "TEXT")
        _ensure_column(conn, "dick_of_day", "chosen_date", "TEXT")
        _ensure_column(conn, "active_duels", "status", "TEXT DEFAULT 'active'")
        _ensure_column(conn, "active_duels", "inline_message_id", "TEXT")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_grow_history_chat "
            "ON grow_history (chat_id, created_at)"
        )


# --- Пользователи и размеры -------------------------------------------------

def get_or_create_user(user_id, chat_id, username=None, first_name=None):
    """Создать запись пользователя или обновить его имя/username."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_sizes WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ).fetchone()

        if row is None:
            conn.execute(
                """INSERT INTO user_sizes (user_id, chat_id, username, first_name)
                   VALUES (?, ?, ?, ?)""",
                (user_id, chat_id, username, first_name),
            )
        elif username is not None or first_name is not None:
            conn.execute(
                """UPDATE user_sizes
                   SET username = COALESCE(?, username),
                       first_name = COALESCE(?, first_name)
                   WHERE user_id = ? AND chat_id = ?""",
                (username, first_name, user_id, chat_id),
            )

        row = conn.execute(
            "SELECT * FROM user_sizes WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ).fetchone()
    return dict(row) if row else None


def get_user_size(user_id, chat_id) -> int:
    """Текущий размер пользователя (0, если записи нет)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT size FROM user_sizes WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ).fetchone()
    return int(row["size"]) if row else 0


def adjust_size(conn, user_id, chat_id, delta):
    """Изменить размер в рамках уже открытого соединения (для дуэлей/казино)."""
    conn.execute(
        """UPDATE user_sizes
           SET size = size + ?, max_size = MAX(max_size, size + ?)
           WHERE user_id = ? AND chat_id = ?""",
        (delta, delta, user_id, chat_id),
    )


def apply_grow(user_id, chat_id, change, username=None, first_name=None):
    """Атомарно применить рост, если пользователь ещё не рос сегодня.

    Возвращает словарь с результатом или ``None``, если сегодня уже рос.
    """
    get_or_create_user(user_id, chat_id, username, first_name)
    today = utils.today_str()
    yesterday = utils.yesterday_str()

    with _connect() as conn:
        row = conn.execute(
            "SELECT grow_streak, last_grow_date FROM user_sizes "
            "WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ).fetchone()

        if row["last_grow_date"] == today:
            return None

        streak = (row["grow_streak"] or 0) + 1 if row["last_grow_date"] == yesterday else 1

        cur = conn.execute(
            """UPDATE user_sizes
               SET size = size + ?,
                   max_size = MAX(max_size, size + ?),
                   grow_streak = ?,
                   last_grow = ?,
                   last_grow_date = ?
               WHERE user_id = ? AND chat_id = ?
                 AND (last_grow_date IS NULL OR last_grow_date <> ?)""",
            (change, change, streak, utils.now().isoformat(), today,
             user_id, chat_id, today),
        )
        if cur.rowcount == 0:
            # Кто-то успел вырасти в параллельном запросе
            return None

        conn.execute(
            "INSERT INTO grow_history (user_id, chat_id, change, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, chat_id, change, utils.now().isoformat()),
        )

        new = conn.execute(
            "SELECT size FROM user_sizes WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ).fetchone()

    return {"change": change, "new_size": int(new["size"]), "streak": streak}


def get_chat_top(chat_id, limit=10):
    """Топ участников чата по размеру."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM user_sizes
               WHERE chat_id = ? AND (last_grow IS NOT NULL OR size <> 0)
               ORDER BY size DESC
               LIMIT ?""",
            (chat_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_weekly_top(chat_id, limit=10, days=7):
    """Топ участников по приросту за последние ``days`` дней."""
    since = (utils.now() - _timedelta(days)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT h.user_id AS user_id,
                      u.username AS username,
                      u.first_name AS first_name,
                      SUM(h.change) AS gain
               FROM grow_history h
               LEFT JOIN user_sizes u
                 ON u.user_id = h.user_id AND u.chat_id = h.chat_id
               WHERE h.chat_id = ? AND h.created_at >= ?
               GROUP BY h.user_id
               ORDER BY gain DESC
               LIMIT ?""",
            (chat_id, since, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _timedelta(days):
    from datetime import timedelta
    return timedelta(days=days)


def get_chat_ids():
    """Список всех известных чатов (для фоновых задач)."""
    with _connect() as conn:
        rows = conn.execute("SELECT DISTINCT chat_id FROM user_sizes").fetchall()
    return [r["chat_id"] for r in rows]


# --- Писюн дня --------------------------------------------------------------

def get_current_dick_of_day(chat_id):
    """Писюн дня, если он уже выбран сегодня, иначе ``None``."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM dick_of_day WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if row and row["chosen_date"] == utils.today_str():
        return dict(row)
    return None


def set_dick_of_day(chat_id):
    """Выбрать случайного участника и начислить ему бонус (раз в сутки)."""
    today = utils.today_str()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT chosen_date FROM dick_of_day WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        if existing and existing["chosen_date"] == today:
            return None

        participants = conn.execute(
            """SELECT * FROM user_sizes
               WHERE chat_id = ? AND (last_grow IS NOT NULL OR size <> 0)""",
            (chat_id,),
        ).fetchall()
        if not participants:
            return None

        winner = dict(random.choice(participants))
        bonus = random.randint(config.DICK_OF_DAY_MIN, config.DICK_OF_DAY_MAX)
        old_size = int(winner["size"])
        new_size = old_size + bonus

        conn.execute(
            "UPDATE user_sizes SET size = size + ?, max_size = MAX(max_size, size + ?), "
            "last_dick_of_day = ? WHERE user_id = ? AND chat_id = ?",
            (bonus, bonus, utils.now().isoformat(), winner["user_id"], chat_id),
        )
        conn.execute(
            """INSERT OR REPLACE INTO dick_of_day
               (chat_id, user_id, bonus, old_size, new_size, chosen_date,
                chosen_at, username, first_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (chat_id, winner["user_id"], bonus, old_size, new_size, today,
             utils.now().isoformat(), winner["username"], winner["first_name"]),
        )

    return {
        "user_id": winner["user_id"],
        "username": winner["username"],
        "first_name": winner["first_name"],
        "bonus": bonus,
        "old_size": old_size,
        "new_size": new_size,
    }


# --- Дуэли ------------------------------------------------------------------

def create_duel(challenger_id, chat_id, bet, inline_message_id=None):
    """Создать активную дуэль, вернуть её id."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO active_duels
               (challenger_id, chat_id, bet, status, inline_message_id, created_at)
               VALUES (?, ?, ?, 'active', ?, ?)""",
            (challenger_id, chat_id, bet, inline_message_id, utils.now().isoformat()),
        )
        return cur.lastrowid


def claim_duel(duel_id, accepter_id):
    """Атомарно «занять» дуэль. Возвращает данные дуэли или ``None``.

    Гонка между несколькими принявшими решается на уровне БД: только один
    ``UPDATE`` переведёт статус из ``active``.
    """
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE active_duels SET status = 'completed' "
            "WHERE duel_id = ? AND status = 'active'",
            (duel_id,),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM active_duels WHERE duel_id = ?", (duel_id,)
        ).fetchone()
    return dict(row) if row else None


def expire_duel(duel_id):
    """Пометить дуэль истёкшей. True, если она была ещё активной."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE active_duels SET status = 'expired' "
            "WHERE duel_id = ? AND status = 'active'",
            (duel_id,),
        )
        return cur.rowcount > 0


def resolve_duel(challenger_id, accepter_id, chat_id, bet, challenger_win_chance=0.5):
    """Начислить/списать ставку и обновить статистику победителя и проигравшего.

    ``challenger_win_chance`` — шанс победы вызвавшего дуэль (по умолчанию 50/50).
    """
    if random.random() < challenger_win_chance:
        winner_id, loser_id = challenger_id, accepter_id
    else:
        winner_id, loser_id = accepter_id, challenger_id

    with _connect() as conn:
        adjust_size(conn, winner_id, chat_id, bet)
        adjust_size(conn, loser_id, chat_id, -bet)
        for uid in (winner_id, loser_id):
            conn.execute(
                "INSERT OR IGNORE INTO duel_stats (user_id, chat_id) VALUES (?, ?)",
                (uid, chat_id),
            )
        conn.execute(
            "UPDATE duel_stats SET wins = wins + 1, total_won = total_won + ? "
            "WHERE user_id = ? AND chat_id = ?",
            (bet, winner_id, chat_id),
        )
        conn.execute(
            "UPDATE duel_stats SET losses = losses + 1, total_won = total_won - ? "
            "WHERE user_id = ? AND chat_id = ?",
            (bet, loser_id, chat_id),
        )
    return winner_id, loser_id


def get_duel_stats(user_id, chat_id):
    """Статистика дуэлей пользователя."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM duel_stats WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ).fetchone()
    if not row:
        return {"wins": 0, "losses": 0, "total_won": 0}
    return dict(row)


# --- Казино -----------------------------------------------------------------

def play_casino(user_id, chat_id, bet, win):
    """Применить результат казино. Возвращает новый размер."""
    delta = bet * (config.CASINO_WIN_MULTIPLIER - 1) if win else -bet
    with _connect() as conn:
        adjust_size(conn, user_id, chat_id, delta)
        row = conn.execute(
            "SELECT size FROM user_sizes WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ).fetchone()
    return int(row["size"]) if row else 0


# --- Достижения -------------------------------------------------------------

def unlock_achievement(user_id, chat_id, code):
    """Разблокировать достижение. True, если оно новое."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO achievements (user_id, chat_id, code, unlocked_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, chat_id, code, utils.now().isoformat()),
        )
        return cur.rowcount > 0


def get_achievements(user_id, chat_id):
    """Список кодов достижений пользователя."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT code FROM achievements WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ).fetchall()
    return [r["code"] for r in rows]


# --- Чаты и связка chat_instance ↔ chat_id ----------------------------------

# Таблицы, где ключ чата нужно переносить при склейке
_CHAT_KEYED_TABLES = (
    "user_sizes", "dick_of_day", "duel_stats",
    "active_duels", "grow_history", "achievements",
)


def record_chat(chat_id, title=None):
    """Отметить, что бот сейчас состоит в чате (для проактивных постов)."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO chats (chat_id, title, is_active, added_at)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(chat_id) DO UPDATE
                 SET is_active = 1, title = COALESCE(excluded.title, chats.title)""",
            (str(chat_id), title, utils.now().isoformat()),
        )


def set_chat_active(chat_id, active):
    """Пометить чат активным/неактивным (бота добавили/удалили)."""
    with _connect() as conn:
        conn.execute(
            "UPDATE chats SET is_active = ? WHERE chat_id = ?",
            (1 if active else 0, str(chat_id)),
        )


def get_active_chats():
    """Чаты, где бот сейчас состоит (для рассылки авто-событий)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT chat_id, title FROM chats WHERE is_active = 1"
        ).fetchall()
    return [dict(r) for r in rows]


def link_chat_instance(chat_instance, chat_id):
    """Связать inline-идентификатор чата с реальным chat_id и перенести данные.

    Возвращает True, если связка новая (перенос выполнен), иначе False.
    """
    if not chat_instance:
        return False
    canonical = str(chat_id)
    with _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM chat_links WHERE chat_instance = ?", (chat_instance,)
        ).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO chat_links (chat_instance, chat_id, linked_at) VALUES (?, ?, ?)",
            (chat_instance, canonical, utils.now().isoformat()),
        )
        if chat_instance != canonical:
            for table in _CHAT_KEYED_TABLES:
                # OR IGNORE: если под chat_id уже есть строка с тем же PK — не рушимся
                conn.execute(
                    f"UPDATE OR IGNORE {table} SET chat_id = ? WHERE chat_id = ?",
                    (canonical, chat_instance),
                )
    return True


def resolve_chat_key(chat_instance):
    """Канонический ключ чата: связанный chat_id (строкой) либо сам chat_instance."""
    if chat_instance is None:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT chat_id FROM chat_links WHERE chat_instance = ?", (chat_instance,)
        ).fetchone()
    return row["chat_id"] if row else str(chat_instance)


# --- RPG-персонаж (глобальный, ключ — user_id) ------------------------------

def get_or_create_player(user_id, username=None, first_name=None):
    """Получить или создать глобального персонажа; обновить имя/username."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM players WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO players (user_id, username, first_name, created_at)
                   VALUES (?, ?, ?, ?)""",
                (user_id, username, first_name, utils.now().isoformat()),
            )
        elif username is not None or first_name is not None:
            conn.execute(
                """UPDATE players
                   SET username = COALESCE(?, username),
                       first_name = COALESCE(?, first_name)
                   WHERE user_id = ?""",
                (username, first_name, user_id),
            )
        row = conn.execute(
            "SELECT * FROM players WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row)


def update_player_progress(user_id, exp, level):
    """Сохранить опыт и уровень персонажа."""
    with _connect() as conn:
        conn.execute(
            "UPDATE players SET exp = ?, level = ? WHERE user_id = ?",
            (exp, level, user_id),
        )


def set_player_class(user_id, klass):
    """Задать класс персонажа."""
    with _connect() as conn:
        conn.execute(
            "UPDATE players SET klass = ? WHERE user_id = ?", (klass, user_id)
        )


def adjust_player_coins(user_id, delta):
    """Изменить баланс монет персонажа, вернуть новый баланс."""
    with _connect() as conn:
        conn.execute(
            "UPDATE players SET coins = coins + ? WHERE user_id = ?",
            (delta, user_id),
        )
        row = conn.execute(
            "SELECT coins FROM players WHERE user_id = ?", (user_id,)
        ).fetchone()
    return int(row["coins"]) if row else 0


# --- Экспедиции -------------------------------------------------------------

def get_active_expedition(user_id):
    """Текущая незавершённая экспедиция игрока или ``None``."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM expeditions WHERE user_id = ? AND status = 'active' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def create_expedition(user_id, zone, chat_key, ends_at):
    """Создать активную экспедицию, вернуть её id."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO expeditions (user_id, zone, chat_key, started_at, ends_at,
                                        status)
               VALUES (?, ?, ?, ?, ?, 'active')""",
            (user_id, zone, chat_key, utils.now().isoformat(), ends_at),
        )
        return cur.lastrowid


def get_pending_expedition_users(chat_key):
    """user_id всех, у кого в этом чате есть вернувшаяся, но не забранная экспедиция."""
    now = utils.now().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM expeditions "
            "WHERE chat_key = ? AND status = 'active' AND ends_at <= ?",
            (str(chat_key), now),
        ).fetchall()
    return [r["user_id"] for r in rows]


def claim_expedition(expedition_id):
    """Атомарно завершить экспедицию. Возвращает её данные или ``None``."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE expeditions SET status = 'claimed' "
            "WHERE id = ? AND status = 'active'",
            (expedition_id,),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT * FROM expeditions WHERE id = ?", (expedition_id,)
        ).fetchone()
    return dict(row) if row else None


# --- Инвентарь и экипировка -------------------------------------------------

def add_item(user_id, template, rarity, slot):
    """Добавить предмет в инвентарь, вернуть его id."""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO player_items (user_id, template, rarity, slot, obtained_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, template, rarity, slot, utils.now().isoformat()),
        )
        return cur.lastrowid


def get_inventory(user_id, limit=None):
    """Предметы игрока (сначала надетые, затем по редкости)."""
    query = "SELECT * FROM player_items WHERE user_id = ? ORDER BY equipped DESC, id DESC"
    params = [user_id]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_equipped(user_id):
    """Надетые предметы игрока."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM player_items WHERE user_id = ? AND equipped = 1",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def equip_item(user_id, item_id):
    """Надеть предмет (сняв другой в том же слоте). True при успехе."""
    with _connect() as conn:
        item = conn.execute(
            "SELECT slot FROM player_items WHERE id = ? AND user_id = ?",
            (item_id, user_id),
        ).fetchone()
        if item is None:
            return False
        conn.execute(
            "UPDATE player_items SET equipped = 0 WHERE user_id = ? AND slot = ?",
            (user_id, item["slot"]),
        )
        conn.execute(
            "UPDATE player_items SET equipped = 1 WHERE id = ? AND user_id = ?",
            (item_id, user_id),
        )
    return True


def unequip_item(user_id, item_id):
    """Снять предмет."""
    with _connect() as conn:
        conn.execute(
            "UPDATE player_items SET equipped = 0 WHERE id = ? AND user_id = ?",
            (item_id, user_id),
        )


# --- Боссы ------------------------------------------------------------------

def get_active_boss(chat_key):
    """Активный босс чата или ``None``."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM bosses WHERE chat_key = ? AND status = 'active' "
            "ORDER BY id DESC LIMIT 1",
            (str(chat_key),),
        ).fetchone()
    return dict(row) if row else None


def spawn_boss(chat_key, name, emoji, max_hp):
    """Заспавнить босса, если в чате нет активного. Вернуть id или ``None``."""
    with _connect() as conn:
        active = conn.execute(
            "SELECT 1 FROM bosses WHERE chat_key = ? AND status = 'active'",
            (str(chat_key),),
        ).fetchone()
        if active:
            return None
        cur = conn.execute(
            """INSERT INTO bosses (chat_key, name, emoji, max_hp, hp, status, spawned_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?)""",
            (str(chat_key), name, emoji, max_hp, max_hp, utils.now().isoformat()),
        )
        return cur.lastrowid


def get_boss_hit(boss_id, user_id):
    """Запись о вкладе игрока в бой (для кулдауна) или ``None``."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM boss_hits WHERE boss_id = ? AND user_id = ?",
            (boss_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def apply_boss_hit(boss_id, user_id, damage):
    """Нанести урону боссу (атомарно) и учесть вклад. Возвращает новый HP."""
    with _connect() as conn:
        conn.execute(
            "UPDATE bosses SET hp = hp - ? WHERE id = ? AND status = 'active'",
            (damage, boss_id),
        )
        conn.execute(
            """INSERT INTO boss_hits (boss_id, user_id, damage, hits, last_hit_at)
               VALUES (?, ?, ?, 1, ?)
               ON CONFLICT(boss_id, user_id) DO UPDATE
                 SET damage = damage + excluded.damage,
                     hits = hits + 1,
                     last_hit_at = excluded.last_hit_at""",
            (boss_id, user_id, damage, utils.now().isoformat()),
        )
        row = conn.execute("SELECT hp FROM bosses WHERE id = ?", (boss_id,)).fetchone()
    return int(row["hp"]) if row else 0


def defeat_boss(boss_id):
    """Атомарно пометить босса поверженным. True, если это сделали мы."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE bosses SET status = 'defeated', defeated_at = ? "
            "WHERE id = ? AND status = 'active'",
            (utils.now().isoformat(), boss_id),
        )
        return cur.rowcount > 0


def get_boss_contributors(boss_id):
    """Участники боя, отсортированные по нанесённому урону (убыв.)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_id, damage, hits FROM boss_hits WHERE boss_id = ? "
            "ORDER BY damage DESC",
            (boss_id,),
        ).fetchall()
    return [dict(r) for r in rows]
