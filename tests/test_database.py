"""Тесты слоя данных на изолированной БД в tmp."""
import importlib

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Свежая БД в отдельном файле для каждого теста."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    import config
    importlib.reload(config)
    import database
    importlib.reload(database)
    database.init_db()
    return database


def test_grow_once_per_day(db):
    first = db.apply_grow(1, "chatA", 5, "user", "User")
    assert first is not None
    assert first["new_size"] == 5
    # Второй раз в те же сутки — запрещено
    assert db.apply_grow(1, "chatA", 5) is None
    assert db.get_user_size(1, "chatA") == 5


def test_grow_streak_resets(db, monkeypatch):
    import utils
    # День 1
    monkeypatch.setattr(utils, "today_str", lambda: "2026-01-01")
    monkeypatch.setattr(utils, "yesterday_str", lambda: "2025-12-31")
    assert db.apply_grow(1, "c", 3)["streak"] == 1
    # День 2 подряд
    monkeypatch.setattr(utils, "today_str", lambda: "2026-01-02")
    monkeypatch.setattr(utils, "yesterday_str", lambda: "2026-01-01")
    assert db.apply_grow(1, "c", 3)["streak"] == 2
    # Пропуск дня — серия сбрасывается
    monkeypatch.setattr(utils, "today_str", lambda: "2026-01-10")
    monkeypatch.setattr(utils, "yesterday_str", lambda: "2026-01-09")
    assert db.apply_grow(1, "c", 3)["streak"] == 1


def test_max_size_tracks_peak(db, monkeypatch):
    import utils
    monkeypatch.setattr(utils, "today_str", lambda: "2026-01-01")
    monkeypatch.setattr(utils, "yesterday_str", lambda: "2025-12-31")
    db.apply_grow(1, "c", 30)
    monkeypatch.setattr(utils, "today_str", lambda: "2026-01-02")
    monkeypatch.setattr(utils, "yesterday_str", lambda: "2026-01-01")
    db.apply_grow(1, "c", -20)  # размер 10, но рекорд остаётся 30
    row = db.get_or_create_user(1, "c")
    assert int(row["size"]) == 10
    assert int(row["max_size"]) == 30


def test_chats_are_isolated(db):
    db.apply_grow(1, "chatA", 5)
    db.apply_grow(1, "chatB", 9)
    assert db.get_user_size(1, "chatA") == 5
    assert db.get_user_size(1, "chatB") == 9


def test_top_orders_by_size(db):
    db.apply_grow(1, "c", 3, "a", "A")
    db.apply_grow(2, "c", 10, "b", "B")
    db.apply_grow(3, "c", 7, "c", "C")
    top = db.get_chat_top("c")
    assert [u["user_id"] for u in top] == [2, 3, 1]


def test_weekly_top_sums_gains(db):
    db.apply_grow(1, "c", 4, "a", "A")
    db.apply_grow(2, "c", 9, "b", "B")
    top = db.get_weekly_top("c")
    assert top[0]["user_id"] == 2
    assert top[0]["gain"] == 9


def test_dick_of_day_once_per_day(db):
    db.apply_grow(1, "c", 5, "a", "A")
    first = db.set_dick_of_day("c")
    assert first is not None
    assert db.set_dick_of_day("c") is None  # уже выбран сегодня
    current = db.get_current_dick_of_day("c")
    assert current["user_id"] == 1


def test_dick_of_day_needs_participants(db):
    assert db.set_dick_of_day("empty") is None


def test_duel_claim_is_atomic(db):
    db.apply_grow(1, "c", 20, "a", "A")
    db.apply_grow(2, "c", 20, "b", "B")
    duel_id = db.create_duel(1, "c", 5)
    # Первый принявший выигрывает гонку
    assert db.claim_duel(duel_id, 2) is not None
    # Второй уже не может — дуэль занята
    assert db.claim_duel(duel_id, 3) is None


def test_duel_expire(db):
    duel_id = db.create_duel(1, "c", 5)
    assert db.expire_duel(duel_id) is True
    assert db.expire_duel(duel_id) is False  # повторно уже нельзя
    assert db.claim_duel(duel_id, 2) is None  # истёкшую нельзя принять


def test_resolve_duel_transfers_and_stats(db):
    db.apply_grow(1, "c", 20, "a", "A")
    db.apply_grow(2, "c", 20, "b", "B")
    winner, loser = db.resolve_duel(1, 2, "c", 5)
    assert db.get_user_size(winner, "c") == 25
    assert db.get_user_size(loser, "c") == 15
    ws = db.get_duel_stats(winner, "c")
    ls = db.get_duel_stats(loser, "c")
    assert ws["wins"] == 1 and ws["total_won"] == 5
    assert ls["losses"] == 1 and ls["total_won"] == -5


def test_casino_win_and_lose(db):
    db.apply_grow(1, "c", 20, "a", "A")
    assert db.play_casino(1, "c", 5, win=True) == 25
    assert db.play_casino(1, "c", 5, win=False) == 20


def test_achievements_unlock_once(db):
    assert db.unlock_achievement(1, "c", "first_grow") is True
    assert db.unlock_achievement(1, "c", "first_grow") is False
    assert db.get_achievements(1, "c") == ["first_grow"]


def test_record_and_active_chats(db):
    db.record_chat(-100500, "My Group")
    assert [c["chat_id"] for c in db.get_active_chats()] == ["-100500"]
    db.set_chat_active(-100500, False)
    assert db.get_active_chats() == []
    # Повторное добавление снова активирует
    db.record_chat(-100500, "My Group")
    assert len(db.get_active_chats()) == 1


def test_link_migrates_inline_data_to_chat_id(db):
    # Данные наиграны в inline-режиме под chat_instance
    inst = "8888888888888888888"
    db.apply_grow(1, inst, 20, "a", "A")
    db.apply_grow(2, inst, 5, "b", "B")
    assert db.get_user_size(1, inst) == 20

    # Бот добавлен в группу → узнали реальный chat_id → склейка
    assert db.link_chat_instance(inst, -100500) is True
    # Повторная склейка ничего не делает
    assert db.link_chat_instance(inst, -100500) is False

    # Данные переехали на канонический ключ (str(chat_id))
    assert db.get_user_size(1, inst) == 0          # под старым ключом пусто
    assert db.get_user_size(1, "-100500") == 20    # под новым — на месте
    assert db.resolve_chat_key(inst) == "-100500"


def test_resolve_unlinked_returns_instance(db):
    assert db.resolve_chat_key("someinstance") == "someinstance"
    assert db.resolve_chat_key(None) is None


def test_link_survives_pk_conflict(db):
    # И под chat_instance, и под chat_id уже есть строка одного пользователя
    inst = "777"
    db.apply_grow(1, inst, 20, "a", "A")
    db.apply_grow(1, "-42", 3, "a", "A")
    # Склейка не должна падать (OR IGNORE), данные под chat_id сохраняются
    assert db.link_chat_instance(inst, -42) is True
    assert db.get_user_size(1, "-42") == 3
