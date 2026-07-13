"""Тесты лута, экспедиций и экипировки."""
import importlib
import random

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "exp.db"))
    import config
    importlib.reload(config)
    import database
    importlib.reload(database)
    import utils
    importlib.reload(utils)
    from game import character, classes, expeditions, leveling, loot
    for m in (leveling, classes, loot, character, expeditions):
        importlib.reload(m)
    database.init_db()
    return {
        "config": config, "database": database, "utils": utils,
        "character": character, "expeditions": expeditions, "loot": loot,
    }


def test_roll_rarity_deterministic(env):
    loot = env["loot"]
    # Малое случайное значение -> самый частый (обычный) тир
    rng = random.Random()
    rng.random = lambda: 0.0
    assert loot.roll_rarity(rng=rng) == "common"


def test_luck_shifts_toward_rare(env):
    loot = env["loot"]
    base = sum(loot.roll_rarity(rng=random.Random(i)) != "common" for i in range(400))
    lucky = sum(loot.roll_rarity(luck=50, rng=random.Random(i)) != "common"
                for i in range(400))
    assert lucky > base  # с удачей чаще выпадает не-обычное


def test_item_bonus_scales_with_rarity(env):
    loot, config = env["loot"], env["config"]
    # Найдём обычное и легендарное оружие
    common = next(c for c, t in config.ITEM_TEMPLATES.items()
                  if t["slot"] == "weapon" and t["rarity"] == "common")
    legend = next(c for c, t in config.ITEM_TEMPLATES.items()
                  if t["slot"] == "weapon" and t["rarity"] == "legendary")
    assert loot.item_bonus(common)["strength"] < loot.item_bonus(legend)["strength"]


def test_expedition_requires_level(env):
    exp = env["expeditions"]
    # Пещеры требуют уровень 6 — новичок не пройдёт
    result = exp.start(1, "caves", "chatA")
    assert isinstance(result, str) and "уровень" in result.lower()


def test_expedition_one_at_a_time(env):
    exp = env["expeditions"]
    assert not isinstance(exp.start(1, "meadow", "chatA"), str)
    assert isinstance(exp.start(1, "meadow", "chatA"), str)  # вторая запрещена


def test_expedition_not_ready_yet(env):
    exp, db = env["expeditions"], env["database"]
    exp.start(1, "meadow", "chatA")
    assert exp.claim(1) is None  # время ещё не вышло
    assert db.get_active_expedition(1) is not None


def test_expedition_claim_gives_rewards(env, monkeypatch):
    exp, db, utils = env["expeditions"], env["database"], env["utils"]
    exp.start(1, "meadow", "chatA")
    # Перематываем время вперёд на 2 часа
    from datetime import timedelta
    real_now = utils.now()
    monkeypatch.setattr(utils, "now", lambda: real_now + timedelta(hours=2))
    reward = exp.claim(1)
    assert reward is not None
    assert reward["exp"] == env["config"].ZONES["meadow"]["exp"]
    assert reward["coins"] >= env["config"].ZONES["meadow"]["coins"][0]
    assert len(db.get_inventory(1)) == 1
    # Повторный забор невозможен
    assert exp.claim(1) is None


def test_equip_applies_stat_bonus(env):
    db, character, config, loot = (env["database"], env["character"],
                                   env["config"], env["loot"])
    character.get_or_create(1)
    weapon = next(c for c, t in config.ITEM_TEMPLATES.items()
                  if t["slot"] == "weapon" and t["rarity"] == "legendary")
    item_id = db.add_item(1, weapon, "legendary", "weapon")
    before = character.effective_stats(db.get_or_create_player(1))["strength"]
    assert db.equip_item(1, item_id) is True
    after = character.effective_stats(db.get_or_create_player(1))["strength"]
    assert after == before + loot.item_bonus(weapon)["strength"]


def test_equip_replaces_same_slot(env):
    db, config = env["database"], env["config"]
    db.get_or_create_player(1)
    w1 = next(c for c, t in config.ITEM_TEMPLATES.items() if t["slot"] == "weapon")
    id1 = db.add_item(1, w1, "common", "weapon")
    id2 = db.add_item(1, w1, "common", "weapon")
    db.equip_item(1, id1)
    db.equip_item(1, id2)  # надеваем второе — первое снимается
    equipped_ids = [i["id"] for i in db.get_equipped(1)]
    assert equipped_ids == [id2]
