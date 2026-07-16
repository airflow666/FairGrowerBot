"""Тесты подземелий: комнаты, бои с мобами, побег, награды, гибель."""
import importlib
import random

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "dng.db"))
    import config
    importlib.reload(config)
    import database
    importlib.reload(database)
    import utils
    importlib.reload(utils)
    from game import character, classes, dungeon, leveling, loot
    for m in (leveling, classes, loot, character, dungeon):
        importlib.reload(m)
    database.init_db()
    return {"config": config, "database": database, "dungeon": dungeon,
            "character": character}


def _give_coins(db, user_id, amount):
    db.get_or_create_player(user_id)
    db.adjust_player_coins(user_id, amount)


def _force_room(monkeypatch, config, room_type):
    """Сделать так, чтобы выпадала только комната нужного типа."""
    monkeypatch.setattr(config, "DUNGEON_ROOM_WEIGHTS", [(room_type, 1.0)])


def _strong_player(db, character, uid, exp=100000):
    db.get_or_create_player(uid)
    character.grant_exp(uid, exp)
    character.set_class(uid, "giga")


def test_enter_requires_coins_and_level(env):
    dungeon, db = env["dungeon"], env["database"]
    db.get_or_create_player(1)
    assert dungeon.enter(1, "rats")["status"] == "no_coins"
    _give_coins(db, 1, 5000)
    assert dungeon.enter(1, "hell")["status"] == "low_level"  # ур. 22 нужен
    assert dungeon.enter(1, "rats")["status"] == "entered"
    assert dungeon.enter(1, "rats")["status"] == "in_run"     # один забег за раз


def test_five_dungeons_gated(env):
    dungeon, config = env["dungeon"], env["config"]
    assert len(config.DUNGEONS) == 5
    lst = dungeon.available_dungeons(1)
    unlocked = [code for code, _, ok in lst if ok]
    assert unlocked == ["rats"]                                # новичку только 1-е


def test_mob_room_blocks_deeper_and_leave(env, monkeypatch):
    dungeon, db, config = env["dungeon"], env["database"], env["config"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    _force_room(monkeypatch, config, "mob")
    r = dungeon.advance(1, rng=random.Random(1))
    assert r["status"] == "mob" and r["mob"]["hp"] > 0
    # Пока моб в комнате: глубже нельзя, уйти нельзя
    assert dungeon.advance(1, rng=random.Random(2))["status"] == "mob_pending"
    assert dungeon.leave(1) is None


def test_fight_strong_player_wins_bounty(env, monkeypatch):
    dungeon, db, character, config = (env["dungeon"], env["database"],
                                      env["character"], env["config"])
    _strong_player(db, character, 1)
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    _force_room(monkeypatch, config, "mob")
    dungeon.advance(1, rng=random.Random(1))
    r = dungeon.fight(1, rng=random.Random(2))
    assert r["status"] == "win"
    assert r["bounty"] > 0
    run = db.get_active_dungeon_run(1)
    assert run["coins_earned"] == r["bounty"]                 # монеты в копилке забега
    assert dungeon.current_mob(run) is None                    # комната очищена


def test_fight_weak_player_dies(env, monkeypatch):
    dungeon, db, config = env["dungeon"], env["database"], env["config"]
    db.get_or_create_player(1)                                 # ур. 1, статы базовые
    _give_coins(db, 1, 5000)
    # Прокачаем уровень руками, чтобы пройти гейт адского подземелья
    db.update_player_progress(1, 10**7, 25)
    dungeon.enter(1, "hell")                                   # мобы 140+ HP, сила 34+
    _force_room(monkeypatch, config, "mob")
    dungeon.advance(1, rng=random.Random(1))
    r = dungeon.fight(1, rng=random.Random(2))
    assert r["status"] == "dead"
    assert db.get_active_dungeon_run(1) is None
    assert len(db.get_inventory(1)) == 0


def test_flee_never_kills(env, monkeypatch):
    dungeon, db, config = env["dungeon"], env["database"], env["config"]
    db.get_or_create_player(1)
    db.update_player_progress(1, 10**7, 25)
    _give_coins(db, 1, 5000)
    dungeon.enter(1, "hell")
    _force_room(monkeypatch, config, "mob")
    dungeon.advance(1, rng=random.Random(1))
    # Даже от самого жирного моба побег оставляет минимум 1 HP
    for seed in range(20):
        r = dungeon.flee(1, rng=random.Random(seed))
        if r["status"] == "fled":
            assert r["hp"] >= 1
            break
    run = db.get_active_dungeon_run(1)
    assert run is not None and dungeon.current_mob(run) is None


def test_treasure_coins_are_random(env, monkeypatch):
    dungeon, db, config = env["dungeon"], env["database"], env["config"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    _force_room(monkeypatch, config, "treasure")
    gains = set()
    for seed in range(15):
        r = dungeon.advance(1, rng=random.Random(seed))
        gains.add(r["gain"])
    assert len(gains) > 3                                      # рандом, не константа


def test_rest_heals_capped(env, monkeypatch):
    dungeon, db, config = env["dungeon"], env["database"], env["config"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    run = db.get_active_dungeon_run(1)
    _force_room(monkeypatch, config, "rest")
    r = dungeon.advance(1, rng=random.Random(1))
    assert r["status"] == "rest"
    assert r["hp"] <= run["max_hp"]                            # не выше максимума


def test_leave_items_respect_floor(env, monkeypatch):
    dungeon, db, config = env["dungeon"], env["database"], env["config"]
    db.get_or_create_player(1)
    db.update_player_progress(1, 10**7, 25)
    _give_coins(db, 1, 5000)
    dungeon.enter(1, "dragon")                                 # loot_floor = rare
    run = db.get_active_dungeon_run(1)
    db.update_dungeon_run(run["id"], 3, run["hp"], 100, 4)     # 4 предмета в закромах
    summary = dungeon.leave(1, rng=random.Random(0))
    order = config.RARITY_ORDER
    for item in summary["items"]:
        assert order.index(item["rarity"]) >= order.index("rare")


def test_trap_can_kill(env, monkeypatch):
    dungeon, db, config = env["dungeon"], env["database"], env["config"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    _force_room(monkeypatch, config, "trap")
    result = {"status": "trap"}
    for seed in range(200):
        result = dungeon.advance(1, rng=random.Random(seed))
        if result["status"] == "dead":
            break
    assert result["status"] == "dead"
    assert dungeon.leave(1) is None
