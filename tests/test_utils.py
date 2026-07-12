"""Тесты форматирования упоминаний (в т.ч. экранирование HTML)."""
from utils import format_mention


def test_username_mention():
    assert format_mention(42, "durov", "Pavel") == "@durov"


def test_first_name_link_when_no_username():
    assert format_mention(42, None, "Pavel") == '<a href="tg://user?id=42">Pavel</a>'


def test_html_in_first_name_is_escaped():
    # Имя с HTML не должно ломать разметку сообщения
    out = format_mention(42, None, "<b>evil</b>")
    assert "<b>evil</b>" not in out
    assert "&lt;b&gt;evil&lt;/b&gt;" in out


def test_fallback_to_user_id():
    assert format_mention(42, None, None) == "User42"
