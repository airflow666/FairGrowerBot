"""Экономика: магазин (сундуки, смена класса) и пассивный доход (ферма)."""
import random
from datetime import datetime

import config
import database
import utils
from game import character, loot

# --- Ферма (пассивный доход) ------------------------------------------------

def property_at(level):
    """Параметры фермы текущего уровня (``level`` >= 1) или ``None``."""
    if level <= 0:
        return None
    return config.PROPERTIES[min(level, len(config.PROPERTIES)) - 1]


def next_property(level):
    """Параметры следующего уровня фермы для покупки/улучшения или ``None``."""
    if level >= len(config.PROPERTIES):
        return None
    return config.PROPERTIES[level]


def pending_income(player) -> int:
    """Накопленный, но не собранный пассивный доход (с учётом капа)."""
    level = player["property_level"] or 0
    prop = property_at(level)
    if not prop or not player["income_at"]:
        return 0
    last = datetime.fromisoformat(player["income_at"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=utils.TZ)
    hours = (utils.now() - last).total_seconds() / 3600
    hours = min(hours, config.PROPERTY_CAP_HOURS)
    return int(prop["rate_per_hour"] * hours)


def claim_income(user_id) -> int:
    """Собрать накопленный доход, вернуть сумму."""
    player = database.get_or_create_player(user_id)
    amount = pending_income(player)
    if amount > 0:
        database.adjust_player_coins(user_id, amount)
    database.set_income_at(user_id, utils.now().isoformat())
    return amount


def upgrade_property(user_id):
    """Купить/улучшить ферму. Возвращает исход (см. ``status``)."""
    player = database.get_or_create_player(user_id)
    level = player["property_level"] or 0
    target = next_property(level)
    if target is None:
        return {"status": "max"}
    if player["coins"] < target["upgrade_cost"]:
        return {"status": "no_coins", "need": target["upgrade_cost"],
                "have": int(player["coins"])}
    claim_income(user_id)  # не теряем накопленное при улучшении
    database.adjust_player_coins(user_id, -target["upgrade_cost"])
    database.set_property_level(user_id, level + 1, utils.now().isoformat())
    return {"status": "upgraded", "level": level + 1, "property": target}


# --- Магазин ----------------------------------------------------------------

def buy_chest(user_id, chest_code, rng=random):
    """Купить сундук — получить случайный предмет. Возвращает исход."""
    chest = config.SHOP_CHESTS.get(chest_code)
    if chest is None:
        return {"status": "bad"}
    player = database.get_or_create_player(user_id)
    if player["coins"] < chest["price"]:
        return {"status": "no_coins", "need": chest["price"],
                "have": int(player["coins"])}
    database.adjust_player_coins(user_id, -chest["price"])
    luck = character.effective_stats(player)["luck"]
    template = loot.roll_item(luck=luck, zone_bonus=chest["bonus"], rng=rng)
    tmpl = config.ITEM_TEMPLATES[template]
    database.add_item(user_id, template, tmpl["rarity"], tmpl["slot"])
    return {"status": "ok", "item": template}


def change_class(user_id, klass):
    """Сменить класс за монеты. Возвращает исход."""
    if klass not in config.CLASSES:
        return {"status": "bad"}
    player = database.get_or_create_player(user_id)
    if player["coins"] < config.CLASS_CHANGE_COST:
        return {"status": "no_coins", "need": config.CLASS_CHANGE_COST,
                "have": int(player["coins"])}
    database.adjust_player_coins(user_id, -config.CLASS_CHANGE_COST)
    database.set_player_class(user_id, klass)
    return {"status": "ok"}
