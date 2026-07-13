"""Тесты подземелий: вход, спуск, ловушки, гибель и выход с добычей."""
import importlib
import random

import pytest


class _AlwaysTreasure(random.Random):
    def random(self):  # noqa: D401 — всегда «не ловушка»
        return 0.99


class _AlwaysTrap(random.Random):
    def random(self):
        return 0.0


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
    assert dungeon.enter(1)["status"] == "no_coins"
    _give_coins(db, 1, 100)
    assert dungeon.enter(1)["status"] == "entered"


def test_enter_deducts_cost(env):
    dungeon, db, config = env["dungeon"], env["database"], env["config"]
    _give_coins(db, 1, 100)
    dungeon.enter(1)
    assert db.get_or_create_player(1)["coins"] == 100 - config.DUNGEON_ENTRY_COST


def test_one_run_at_a_time(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 100)
    dungeon.enter(1)
    assert dungeon.enter(1)["status"] == "in_run"


def test_treasure_accumulates(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 100)
    dungeon.enter(1)
    rng = _AlwaysTreasure()
    r1 = dungeon.advance(1, rng=rng)
    r2 = dungeon.advance(1, rng=rng)
    assert r1["status"] == "treasure" and r2["status"] == "treasure"
    assert r2["depth"] == 2 and r2["treasures"] == 2
    assert r2["coins"] > r1["coins"]


def test_leave_banks_rewards(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 100)
    dungeon.enter(1)
    rng = _AlwaysTreasure()
    dungeon.advance(1, rng=rng)
    dungeon.advance(1, rng=rng)
    coins_before = db.get_or_create_player(1)["coins"]
    summary = dungeon.leave(1, rng=random.Random(0))
    assert summary["depth"] == 2
    assert len(summary["items"]) == 2  # по сундуку на глубину
    assert db.get_or_create_player(1)["coins"] == coins_before + summary["coins"]
    assert len(db.get_inventory(1)) == 2
    assert db.get_active_dungeon_run(1) is None


def test_death_loses_everything(env):
    dungeon, db = env["dungeon"], env["database"]
    _give_coins(db, 1, 100)
    dungeon.enter(1)
    # Ловушки каждый шаг — рано или поздно смерть; урон растёт с глубиной
    rng = _AlwaysTrap()
    result = {"status": "trap"}
    for _ in range(50):
        result = dungeon.advance(1, rng=rng)
        if result["status"] == "dead":
            break
    assert result["status"] == "dead"
    assert db.get_active_dungeon_run(1) is None
    assert len(db.get_inventory(1)) == 0          # добыча потеряна
    # Повторный уход невозможен
    assert dungeon.leave(1) is None


def test_leave_without_run(env):
    assert env["dungeon"].leave(1) is None
