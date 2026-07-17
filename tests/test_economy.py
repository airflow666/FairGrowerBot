"""Тесты экономики: магазин (сундуки, смена класса) и пассивный доход."""
import importlib
import random
from datetime import timedelta

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "eco.db"))
    import config
    importlib.reload(config)
    import database
    importlib.reload(database)
    import utils
    importlib.reload(utils)
    from game import character, classes, economy, leveling, loot
    for m in (leveling, classes, loot, character, economy):
        importlib.reload(m)
    database.init_db()
    return {"config": config, "database": database, "utils": utils,
            "economy": economy}


def _coins(db, uid, amount):
    db.get_or_create_player(uid)
    db.adjust_player_coins(uid, amount)


def test_buy_chest_needs_coins(env):
    eco, db = env["economy"], env["database"]
    db.get_or_create_player(1)
    assert eco.buy_chest(1, "wooden")["status"] == "no_coins"
    _coins(db, 1, 100)
    r = eco.buy_chest(1, "wooden", rng=random.Random(0))
    assert r["status"] == "ok"
    assert len(db.get_inventory(1)) == 1


def test_buy_chest_deducts_price(env):
    eco, db, config = env["economy"], env["database"], env["config"]
    _coins(db, 1, 100)
    eco.buy_chest(1, "wooden", rng=random.Random(0))
    assert db.get_or_create_player(1)["coins"] == 100 - config.SHOP_CHESTS["wooden"]["price"]


def test_floored_chest_guarantees_minimum(env):
    eco, db, config = env["economy"], env["database"], env["config"]
    order = config.RARITY_ORDER
    _coins(db, 1, 10**7)
    # Платиновый — гарантия от 🔵 (rare); за много покупок ни разу не ниже
    floor = config.SHOP_CHESTS["platinum"]["floor"]
    for seed in range(60):
        r = eco.buy_chest(1, "platinum", rng=random.Random(seed))
        assert r["status"] == "ok"
        assert order.index(r["item"]["rarity"]) >= order.index(floor)
    # Королевский — гарантия от 🟣 (epic)
    royal_floor = config.SHOP_CHESTS["royal"]["floor"]
    for seed in range(60):
        r = eco.buy_chest(1, "royal", rng=random.Random(seed + 500))
        assert order.index(r["item"]["rarity"]) >= order.index(royal_floor)


def test_luck_shifts_chest_rolls_up(env):
    eco, db, config = env["economy"], env["database"], env["config"]
    from game import character
    order = config.RARITY_ORDER

    def avg_tier(uid, samples):
        total = 0
        for seed in range(samples):
            r = eco.buy_chest(uid, "wooden", rng=random.Random(seed))
            total += order.index(r["item"]["rarity"])
        return total / samples

    # Новичок без Удачи
    _coins(db, 1, 10**7)
    low = avg_tier(1, 400)
    # Игрок с прокачанной Удачей
    db.get_or_create_player(2)
    character.grant_exp(2, 10**7)
    character.set_class(2, "lucky")
    _coins(db, 2, 10**7)
    for _ in range(30):                       # вложим свободные очки в удачу
        character.train_stat(2, "luck")
    high = avg_tier(2, 400)
    assert high > low                          # удача поднимает средний тир


def test_luck_affects_expensive_chest(env):
    """Регресс A3: Удача должна двигать ролл и на дорогих сундуках с высоким
    zone_bonus (раньше общий кап её полностью съедал на золотом+)."""
    eco, db, config = env["economy"], env["database"], env["config"]
    from game import character
    order = config.RARITY_ORDER

    def avg_tier(uid):
        total = 0
        for seed in range(400):
            r = eco.buy_chest(uid, "golden", rng=random.Random(seed))
            total += order.index(r["item"]["rarity"])
        return total / 400

    _coins(db, 1, 10**8)
    low = avg_tier(1)
    db.get_or_create_player(2)
    character.grant_exp(2, 10**7)
    character.set_class(2, "lucky")
    _coins(db, 2, 10**8)
    for _ in range(30):
        character.train_stat(2, "luck")
    assert avg_tier(2) > low


def test_craft_chain_to_top_tier(env):
    eco, db, config = env["economy"], env["database"], env["config"]
    from game import loot
    db.get_or_create_player(1)
    tiers = config.RARITY_ORDER
    # relic -> cosmic -> godlike, затем крафт с потолка запрещён
    for _ in range(5):
        db.add_item(1, loot.generate_of_rarity("relic", rng=random.Random(7)))
    r = eco.craft(1, "relic", rng=random.Random(8))
    assert r["status"] == "ok" and r["item"]["rarity"] == "cosmic"
    for _ in range(4):
        db.add_item(1, loot.generate_of_rarity("cosmic", rng=random.Random(9)))
    r = eco.craft(1, "cosmic", rng=random.Random(10))  # теперь 5 космических
    assert r["status"] == "ok" and r["item"]["rarity"] == "godlike"
    # Абсолют — потолок, крафт запрещён
    for _ in range(5):
        db.add_item(1, loot.generate_of_rarity("godlike", rng=random.Random(11)))
    assert eco.craft(1, "godlike")["status"] == "max_tier"
    assert tiers[-1] == "godlike"


def test_new_tiers_have_sell_prices(env):
    config = env["config"]
    for rarity in config.RARITY_ORDER:
        assert rarity in config.SELL_PRICES
    # Цены строго растут с тиром
    prices = [config.SELL_PRICES[r] for r in config.RARITY_ORDER]
    assert prices == sorted(prices)
    assert prices == sorted(set(prices))       # без плато


def test_change_class_costs_coins(env):
    eco, db, config = env["economy"], env["database"], env["config"]
    _coins(db, 1, config.CLASS_CHANGE_COST)
    assert eco.change_class(1, "giga")["status"] == "ok"
    assert db.get_or_create_player(1)["klass"] == "giga"
    assert db.get_or_create_player(1)["coins"] == 0
    # Больше монет нет — второй раз нельзя
    assert eco.change_class(1, "tank")["status"] == "no_coins"


def test_buy_first_property(env):
    eco, db = env["economy"], env["database"]
    _coins(db, 1, 100)
    r = eco.upgrade_property(1)
    assert r["status"] == "upgraded" and r["level"] == 1
    assert db.get_or_create_player(1)["property_level"] == 1


def test_property_income_accrues_and_caps(env, monkeypatch):
    eco, db, utils, config = (env["economy"], env["database"], env["utils"],
                              env["config"])
    _coins(db, 1, 100)
    eco.upgrade_property(1)  # Грядка, 5/час
    rate = config.PROPERTIES[0]["rate_per_hour"]

    real = utils.now()
    monkeypatch.setattr(utils, "now", lambda: real + timedelta(hours=3))
    assert eco.pending_income(db.get_or_create_player(1)) == rate * 3

    # За пределами капа доход не растёт
    monkeypatch.setattr(utils, "now",
                        lambda: real + timedelta(hours=config.PROPERTY_CAP_HOURS + 10))
    assert eco.pending_income(db.get_or_create_player(1)) == rate * config.PROPERTY_CAP_HOURS


def test_claim_income_pays_and_resets(env, monkeypatch):
    eco, db, utils = env["economy"], env["database"], env["utils"]
    _coins(db, 1, 100)
    eco.upgrade_property(1)
    coins_after_buy = db.get_or_create_player(1)["coins"]
    real = utils.now()
    monkeypatch.setattr(utils, "now", lambda: real + timedelta(hours=4))
    got = eco.claim_income(1)
    assert got == 5 * 4
    assert db.get_or_create_player(1)["coins"] == coins_after_buy + got
    # Сразу после сбора — пусто
    assert eco.pending_income(db.get_or_create_player(1)) == 0


def test_upgrade_preserves_pending_income(env, monkeypatch):
    eco, db, utils = env["economy"], env["database"], env["utils"]
    _coins(db, 1, 1000)
    eco.upgrade_property(1)  # Грядка (5/час), потратили 100
    real = utils.now()
    monkeypatch.setattr(utils, "now", lambda: real + timedelta(hours=5))
    before = db.get_or_create_player(1)["coins"]
    eco.upgrade_property(1)  # Теплица: сначала соберётся доход 25, потом спишется 300
    after = db.get_or_create_player(1)["coins"]
    assert after == before + 25 - 300
    assert db.get_or_create_player(1)["property_level"] == 2


def test_property_max_level(env):
    eco, db, config = env["economy"], env["database"], env["config"]
    _coins(db, 1, 100000)
    for _ in range(len(config.PROPERTIES)):
        eco.upgrade_property(1)
    assert eco.upgrade_property(1)["status"] == "max"


def test_sell_item_and_bulk(env):
    eco, db, config = env["economy"], env["database"], env["config"]
    from game import loot
    db.get_or_create_player(1)
    inst = loot.generate_of_rarity("rare", rng=random.Random(1))
    item_id = db.add_item(1, inst)
    price = eco.sell_item(1, item_id)
    assert price == config.SELL_PRICES["rare"]
    assert db.get_or_create_player(1)["coins"] == price
    assert len(db.get_inventory(1)) == 0
    # bulk
    for _ in range(3):
        db.add_item(1, loot.generate_of_rarity("common", rng=random.Random(2)))
    count, coins = eco.sell_all(1, "common")
    assert count == 3 and coins == 3 * config.SELL_PRICES["common"]


def test_sell_equipped_blocked(env):
    eco, db = env["economy"], env["database"]
    from game import loot
    db.get_or_create_player(1)
    item_id = db.add_item(1, loot.generate_of_rarity("epic", rng=random.Random(1)))
    db.equip_item(1, item_id)
    assert eco.sell_item(1, item_id) is None  # надетый не продать


def test_convert_cm_to_coins(env):
    eco, db, config = env["economy"], env["database"], env["config"]
    db.apply_grow(1, "chatA", 100, "a", "A")  # 100 см
    r = eco.convert_cm(1, "chatA", 50)
    assert r["status"] == "ok" and r["coins"] == 50 // config.CM_PER_COIN
    assert db.get_user_size(1, "chatA") == 50
    assert db.get_or_create_player(1)["coins"] == r["coins"]
    # Больше, чем есть — отказ
    assert eco.convert_cm(1, "chatA", 999)["status"] == "no_size"


def test_casino_coins(env):
    eco, db = env["economy"], env["database"]
    db.get_or_create_player(1)
    db.adjust_player_coins(1, 100)
    assert eco.play_casino(1, 10, win=True) == 110
    assert eco.play_casino(1, 10, win=False) == 100


def test_craft_needs_five_and_upgrades(env):
    eco, db = env["economy"], env["database"]
    from game import loot
    db.get_or_create_player(1)
    assert eco.craft(1, "common")["status"] == "not_enough"
    for _ in range(5):
        db.add_item(1, loot.generate_of_rarity("common", rng=random.Random(3)))
    r = eco.craft(1, "common", rng=random.Random(4))
    assert r["status"] == "ok"
    assert r["item"]["rarity"] == "uncommon"       # тир выше
    assert db.count_items_by_rarity(1, "common") == 0  # 5 списаны
    assert len(db.get_inventory(1)) == 1


def test_craft_ignores_equipped(env):
    eco, db = env["economy"], env["database"]
    from game import loot
    db.get_or_create_player(1)
    ids = [db.add_item(1, loot.generate_of_rarity("rare", rng=random.Random(i)))
           for i in range(5)]
    db.equip_item(1, ids[0])          # один надет
    # ненадетых только 4 -> крафт запрещён
    assert eco.craft(1, "rare")["status"] == "not_enough"
