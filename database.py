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


def resolve_duel(challenger_id, accepter_id, chat_id, bet):
    """Начислить/списать ставку и обновить статистику победителя и проигравшего."""
    winner_id = random.choice([challenger_id, accepter_id])
    loser_id = accepter_id if winner_id == challenger_id else challenger_id

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
