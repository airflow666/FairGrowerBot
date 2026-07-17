"""Тесты боя с боссом: спавн, урон, кулдаун, победа и раздача наград."""
import importlib
import random

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "boss.db"))
    import config
    importlib.reload(config)
    import database
    importlib.reload(database)
    import utils
    importlib.reload(utils)
    from game import boss, character, classes, leveling, loot
    for m in (leveling, classes, loot, character, boss):
        importlib.reload(m)
    database.init_db()
    return {"config": config, "database": database, "utils": utils,
            "boss": boss, "character": character}


def test_summon_is_singleton(env):
    boss = env["boss"]
    b1, new1 = boss.summon("chatA")
    assert new1 is True
    b2, new2 = boss.summon("chatA")
    assert new2 is False and b2["id"] == b1["id"]  # тот же босс


def test_hit_reduces_hp_and_tracks_damage(env):
    boss, db = env["boss"], env["database"]
    boss.summon("chatA")
    r = boss.hit(1, "chatA", rng=random.Random(1))
    assert r["status"] == "hit"
    assert r["hp"] < r["max_hp"]
    contrib = db.get_boss_contributors(db.get_active_boss("chatA")["id"])
    assert contrib[0]["user_id"] == 1 and contrib[0]["damage"] > 0


def test_cooldown_blocks_second_hit(env):
    boss = env["boss"]
    boss.summon("chatA")
    assert boss.hit(1, "chatA")["status"] == "hit"
    assert boss.hit(1, "chatA")["status"] == "cooldown"


def test_cooldown_expires(env, monkeypatch):
    boss, utils, config = env["boss"], env["utils"], env["config"]
    boss.summon("chatA")
    boss.hit(1, "chatA")
    from datetime import timedelta
    real = utils.now()
    monkeypatch.setattr(utils, "now",
                        lambda: real + timedelta(seconds=config.BOSS_HIT_COOLDOWN + 1))
    assert boss.hit(1, "chatA")["status"] == "hit"


def test_kill_distributes_rewards(env, monkeypatch):
    boss, db, config = env["boss"], env["database"], env["config"]
    # Слабый босс, чтобы добить за пару ударов
    monkeypatch.setattr(config, "BOSS_TEMPLATES", [{"emoji": "👹", "name": "Слизень", "hp": 1}])
    boss.summon("chatA")
    result = boss.hit(1, "chatA", rng=random.Random(5))
    assert result["status"] == "killed"
    rewards = result["rewards"]
    assert rewards[0]["user_id"] == 1 and rewards[0]["top"] is True
    assert rewards[0]["coins"] > 0
    # Получен предмет и монеты
    assert len(db.get_inventory(1)) == 1
    assert db.get_or_create_player(1)["coins"] > 0
    # Босса больше нет
    assert db.get_active_boss("chatA") is None


def test_hit_after_defeat_reports_no_boss(env, monkeypatch):
    boss, config = env["boss"], env["config"]
    monkeypatch.setattr(config, "BOSS_TEMPLATES", [{"emoji": "👹", "name": "Слизень", "hp": 1}])
    boss.summon("chatA")
    boss.hit(1, "chatA")
    assert boss.hit(2, "chatA")["status"] == "no_boss"


def test_reward_split_by_damage(env, monkeypatch):
    boss, db, config = env["boss"], env["database"], env["config"]
    monkeypatch.setattr(config, "BOSS_TEMPLATES", [{"emoji": "👹", "name": "Голем", "hp": 40}])
    b, _ = boss.summon("chatA")
    bid = b["id"]
    # Вручную зададим неравный вклад, затем добьём
    db.apply_boss_hit(bid, 1, 30, config.BOSS_HIT_COOLDOWN)
    db.apply_boss_hit(bid, 2, 9, config.BOSS_HIT_COOLDOWN)
    boss.hit(3, "chatA", rng=random.Random(0))  # добивает
    # Игрок 1 (больше урона) получил больше монет, чем игрок 2
    c1 = db.get_or_create_player(1)["coins"]
    c2 = db.get_or_create_player(2)["coins"]
    assert c1 > c2


def test_length_adds_boss_damage(env, monkeypatch):
    boss, db, config = env["boss"], env["database"], env["config"]
    import random
    # Фикс rng, чтобы сравнивать чистый вклад длины
    monkeypatch.setattr(config, "BOSS_TEMPLATES", [{"emoji": "👹", "name": "X", "hp": 100000}])
    boss.summon("c")
    db.get_or_create_player(1)
    r_small = boss.hit(1, "c", rng=random.Random(0))
    # игрок 2 с большой длиной бьёт сильнее при том же rng
    boss.summon("c2")
    db.get_or_create_player(2)
    db.add_user_size(2, "c2", 1000)  # +10 урона за 1000 см (по 100)
    r_big = boss.hit(2, "c2", rng=random.Random(0))
    assert r_big["damage"] > r_small["damage"]


def test_boss_loot_floor_by_share(env):
    boss = env["boss"]
    assert boss.loot_floor_for_share(0.5) == "legendary"
    assert boss.loot_floor_for_share(0.25) == "epic"
    assert boss.loot_floor_for_share(0.1) == "rare"
    assert boss.loot_floor_for_share(0.01) == "uncommon"


def test_boss_drop_respects_floor(env, monkeypatch):
    boss, db, config = env["boss"], env["database"], env["config"]
    import random
    monkeypatch.setattr(config, "BOSS_TEMPLATES",
                        [{"emoji": "👹", "name": "X", "hp": 400}])
    b, _ = boss.summon("chatF")
    # Игрок 1 ~75% урона, игрок 2 ~22% (добивка игрока 3 размоет чуть-чуть)
    db.apply_boss_hit(b["id"], 1, 300, config.BOSS_HIT_COOLDOWN)
    db.apply_boss_hit(b["id"], 2, 90, config.BOSS_HIT_COOLDOWN)
    result = boss.hit(3, "chatF", rng=random.Random(0))
    assert result["status"] == "killed"
    order = config.RARITY_ORDER
    by_uid = {r["user_id"]: r for r in result["rewards"]}
    # 75% доля -> минимум legendary (или выше за счёт тир-апа топа)
    assert order.index(by_uid[1]["item"]["rarity"]) >= order.index("legendary")
    # 20%+ доля -> минимум epic
    assert order.index(by_uid[2]["item"]["rarity"]) >= order.index("epic")
