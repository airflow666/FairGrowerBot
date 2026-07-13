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
