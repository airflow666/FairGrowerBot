"""Тесты подземелий: вход, гейтинг, растущий риск, добыча, гибель."""
import importlib
import random

import pytest


class _Scripted(random.Random):
    """rng с заданной последовательностью random() (циклится)."""

    def __init__(self, values):
        super().__init__()
        self._v = list(values)
        self._i = 0

    def random(self):
        v = self._v[self._i % len(self._v)]
        self._i += 1
        return v


# В advance() два вызова random(): 1-й — ловушка, 2-й — есть ли предмет.
_TREASURE_WITH_ITEM = _Scripted([0.99, 0.0])   # не ловушка, предмет найден
_TREASURE_NO_ITEM = _Scripted([0.99, 0.99])    # не ловушка, без предмета
_ALWAYS_TRAP = _Scripted([0.0])                 # всегда ловушка


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


def test_enter_requires_coins(env):
    dungeon, db = env["dungeon"], env["database"]
    assert dungeon.enter(1, "rats")["status"] == "no_coins"
    _give_coins(db, 1, 100)
    assert dungeon.enter(1, "rats")["status"] == "entered"


def test_enter_deducts_cost(env):
    dungeon, db, config = env["dungeon"], env["database"], env["config"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    cost = config.DUNGEONS["rats"]["entry_cost"]
    assert db.get_or_create_player(1)["coins"] == 100 - cost


def test_high_dungeon_needs_level(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 1000)
    # Новичок (ур. 1) не войдёт в драконье логово
    assert dungeon.enter(1, "dragon")["status"] == "low_level"


def test_one_run_at_a_time(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    assert dungeon.enter(1, "rats")["status"] == "in_run"


def test_trap_chance_grows_with_depth(env):
    dungeon, config = env["dungeon"], env["config"]
    d = config.DUNGEONS["rats"]
    assert dungeon.trap_chance(d, 1) < dungeon.trap_chance(d, 10)
    assert dungeon.trap_chance(d, 100) <= d["trap_cap"]  # с капом


def test_item_not_every_room(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    r = dungeon.advance(1, rng=_Scripted([0.99, 0.99]))  # комната без предмета
    assert r["status"] == "treasure"
    assert r["treasures"] == 0 and r["coins"] > 0  # монеты есть, предмета нет


def test_treasure_with_item_accumulates(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    rng = _Scripted([0.99, 0.0])
    r1 = dungeon.advance(1, rng=rng)
    r2 = dungeon.advance(1, rng=rng)
    assert r1["found_item"] and r2["found_item"]
    assert r2["depth"] == 2 and r2["treasures"] == 2
    assert r2["coins"] > r1["coins"]


def test_leave_banks_rewards(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    rng = _Scripted([0.99, 0.0])
    dungeon.advance(1, rng=rng)
    dungeon.advance(1, rng=rng)
    coins_before = db.get_or_create_player(1)["coins"]
    summary = dungeon.leave(1, rng=random.Random(0))
    assert summary["depth"] == 2
    assert len(summary["items"]) == 2  # по предмету на найденную добычу
    assert db.get_or_create_player(1)["coins"] == coins_before + summary["coins"]
    assert len(db.get_inventory(1)) == 2
    assert db.get_active_dungeon_run(1) is None


def test_death_loses_everything(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 100)
    dungeon.enter(1, "rats")
    rng = _Scripted([0.0])  # ловушка каждый шаг; урон растёт с глубиной
    result = {"status": "trap"}
    for _ in range(50):
        result = dungeon.advance(1, rng=rng)
        if result["status"] == "dead":
            break
    assert result["status"] == "dead"
    assert db.get_active_dungeon_run(1) is None
    assert len(db.get_inventory(1)) == 0          # добыча потеряна
    assert dungeon.leave(1) is None               # повторный уход невозможен


def test_leave_without_run(env):
    assert env["dungeon"].leave(1) is None
