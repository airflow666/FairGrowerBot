"""Тесты RPG-логики: уровни, классы, характеристики, персонаж."""
import importlib

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Свежая БД + перезагруженные модули игры."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "game.db"))
    import config
    importlib.reload(config)
    import database
    importlib.reload(database)
    from game import character, classes, leveling
    importlib.reload(leveling)
    importlib.reload(classes)
    importlib.reload(character)
    database.init_db()
    return database, leveling, classes, character


def test_level_curve(env):
    _, leveling, _, _ = env
    # LEVEL_STEP=100: уровень 2 при 100 XP, уровень 3 при 300 XP
    assert leveling.exp_to_reach(1) == 0
    assert leveling.exp_to_reach(2) == 100
    assert leveling.exp_to_reach(3) == 300
    assert leveling.level_for_exp(0) == 1
    assert leveling.level_for_exp(99) == 1
    assert leveling.level_for_exp(100) == 2
    assert leveling.level_for_exp(299) == 2
    assert leveling.level_for_exp(300) == 3


def test_progress_within_level(env):
    _, leveling, _, _ = env
    level, into, need = leveling.progress(150)
    assert level == 2
    assert into == 50           # 150 - 100
    assert need == 200          # 300 - 100


def test_stats_distribution_by_class(env):
    _, _, classes, _ = env
    # Гигачлен вкладывается в Силу — она заметно выше базы и прочих статов
    giga = classes.stats_for(11, "giga")
    assert giga["strength"] > 5
    assert giga["strength"] > giga["vitality"]
    assert giga["strength"] > giga["luck"]
    # Без класса — равномерно по всем 5 статам
    none = classes.stats_for(11, None)
    assert len(set(none.values())) == 1


def test_level_1_is_base_stats(env):
    _, _, classes, _ = env
    s = classes.stats_for(1, "giga")
    # На 1 уровне все характеристики — базовые (5)
    assert set(s) == {"strength", "vitality", "luck", "crit", "speed"}
    assert all(v == 5 for v in s.values())


def test_grant_exp_and_level_up(env):
    _, _, _, character = env
    r = character.grant_exp(1, 50, "a", "A")
    assert r["level"] == 1 and r["level_up"] == 0
    r = character.grant_exp(1, 60)           # всего 110 -> уровень 2
    assert r["level"] == 2 and r["level_up"] == 1


def test_set_class_persists(env):
    database, _, _, character = env
    assert character.set_class(1, "tank") is True
    assert character.set_class(1, "nonexistent") is False
    assert database.get_or_create_player(1)["klass"] == "tank"


def test_duel_win_chance_clamped(env):
    database, _, _, character = env
    # Прокачиваем игрока 1 до высокого уровня, игрок 2 — новичок
    character.grant_exp(1, 100000)
    character.set_class(1, "giga")
    chance = character.duel_win_chance(1, 2, "c")
    assert chance <= 0.65                      # ограничено сверху
    # Обратный расклад — ограничено снизу
    assert character.duel_win_chance(2, 1, "c") >= 0.35


def test_coins_adjust(env):
    database, _, _, _ = env
    database.get_or_create_player(1)
    assert database.adjust_player_coins(1, 50) == 50
    assert database.adjust_player_coins(1, -20) == 30


def test_length_influences_duel(env):
    database, _, _, character = env
    # Равные персонажи, но у игрока 1 длина сильно больше -> шанс выше 0.5
    database.add_user_size(1, "c", 500)
    base = character.duel_win_chance(1, 2, "c")
    assert base > 0.5


def test_title_by_length(env):
    import utils
    assert "Корнишон" in utils.title_for(50)
    assert "Микропенис" in utils.title_for(-5)
    assert "Орбитальный" in utils.title_for(3000)
