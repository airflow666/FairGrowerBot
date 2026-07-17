"""Тесты слоя хендлеров: владелец меню, дисциплина ответа, протухание дуэли.

Реального Telegram нет — используем лёгкие фейки query/context и гоняем
асинхронные хендлеры через ``asyncio.run``. Главное, что здесь ловится:
owner-guard меню, единственный ответ на callback и ленивое протухание вызова.
"""
import asyncio
import importlib
from datetime import timedelta

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "h.db"))
    import config
    importlib.reload(config)
    import database
    importlib.reload(database)
    import utils
    importlib.reload(utils)
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
    for m in (leveling, classes, loot, character, economy, expeditions, boss,
              dungeon):
        importlib.reload(m)
    import handlers
    importlib.reload(handlers)
    database.init_db()
    return {"config": config, "database": database, "utils": utils,
            "handlers": handlers}


class FakeUser:
    def __init__(self, uid, username="u", first_name="U"):
        self.id = uid
        self.username = username
        self.first_name = first_name


class FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id
        self.type = "supergroup"


class FakeMessage:
    def __init__(self, chat_id):
        self.chat = FakeChat(chat_id)
        self.message_id = 1


class FakeQuery:
    """Минимальный callback-query: считает ответы и правки сообщения."""

    def __init__(self, uid, data="", chat_id=-100, with_message=True):
        self.from_user = FakeUser(uid)
        self.data = data
        self.message = FakeMessage(chat_id) if with_message else None
        self.chat_instance = "inst"
        self.inline_message_id = None
        self.answers = []
        self.edits = []
        self._answered = False

    async def answer(self, text=None, show_alert=False):
        # Реальный Telegram бросает на повторный ответ — эмулируем
        if self._answered:
            raise RuntimeError("query already answered")
        self._answered = True
        self.answers.append({"text": text, "alert": show_alert})

    async def edit_message_text(self, text, **kwargs):
        self.edits.append({"text": text, **kwargs})


class FakeContext:
    job_queue = None


def _run(coro):
    return asyncio.run(coro)


def test_nav_owner_guard_blocks_stranger(env):
    handlers = env["handlers"]
    # Меню принадлежит 111, жмёт 222 -> отказ попапом, без правки экрана
    q = FakeQuery(222, data="nav_111_profile")
    _run(handlers._nav(q, FakeContext(), "c", "111_profile"))
    assert q.edits == []
    assert q.answers and q.answers[-1]["alert"] is True


def test_nav_owner_can_open(env):
    handlers = env["handlers"]
    q = FakeQuery(111, data="nav_111_profile")
    _run(handlers._nav(q, FakeContext(), "c", "111_profile"))
    assert q.edits                                  # экран профиля отрисован
    assert "👤" in q.edits[-1]["text"]              # это действительно профиль


def test_handle_button_answers_once(env):
    handlers = env["handlers"]
    # Неизвестный data: ни одна ветка не сработала, но finally гасит спиннер
    q = FakeQuery(1, data="totally_unknown")
    _run(handlers.handle_button(_Update(q), FakeContext()))
    # Ровно один ответ (повторный бросил бы и был бы проглочен)
    assert len(q.answers) == 1


def test_duel_stale_detection(env):
    handlers, utils, config = env["handlers"], env["utils"], env["config"]
    fresh = {"created_at": utils.now().isoformat()}
    old = {"created_at": (utils.now()
                          - timedelta(seconds=config.DUEL_TIMEOUT + 5)).isoformat()}
    assert handlers._duel_is_stale(fresh) is False
    assert handlers._duel_is_stale(old) is True
    assert handlers._duel_is_stale({"created_at": None}) is False


class _Update:
    """Обёртка, как ждёт handle_button (update.callback_query)."""

    def __init__(self, query):
        self.callback_query = query
