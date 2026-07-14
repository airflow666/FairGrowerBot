"""Вспомогательные функции: работа со временем и форматирование имён."""
import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

# Часовой пояс, по которому считаются сутки
TZ = ZoneInfo(config.TIMEZONE)


def now() -> datetime:
    """Текущее время в настроенном часовом поясе."""
    return datetime.now(TZ)


def today_str() -> str:
    """Сегодняшняя дата (YYYY-MM-DD) в настроенном часовом поясе."""
    return now().strftime("%Y-%m-%d")


def yesterday_str() -> str:
    """Вчерашняя дата (YYYY-MM-DD) в настроенном часовом поясе."""
    return (now() - timedelta(days=1)).strftime("%Y-%m-%d")


def format_mention(user_id, username=None, first_name=None) -> str:
    """Упоминание пользователя для HTML-сообщения.

    Пользовательские данные экранируются, чтобы имя вида ``<b>`` не ломало
    разметку сообщения.
    """
    if username:
        return f"@{html.escape(str(username))}"
    if first_name:
        return f'<a href="tg://user?id={user_id}">{html.escape(str(first_name))}</a>'
    return f"User{user_id}"


def title_for(size) -> str:
    """Титул по длине (чатовой): «🍆 Уважаемый Шланг»."""
    for threshold, emoji, name in config.TITLES:
        if size >= threshold:
            return f"{emoji} {name}"
    return ""
