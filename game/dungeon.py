"""Подземелья: push-your-luck забег.

Игрок платит за вход, спускается всё глубже. На каждом шаге — либо сундук
(монеты + будущий лут), либо ловушка (урон). Можно уйти с накопленной добычей
или погибнуть и потерять всё (включая плату за вход).
"""
import random

import config
import database
from game import character, loot


def enter(user_id):
    """Войти в подземелье. Возвращает словарь с исходом (см. ``status``)."""
    if database.get_active_dungeon_run(user_id) is not None:
        return {"status": "in_run", "run": database.get_active_dungeon_run(user_id)}
    player = database.get_or_create_player(user_id)
    if player["coins"] < config.DUNGEON_ENTRY_COST:
        return {"status": "no_coins", "need": config.DUNGEON_ENTRY_COST,
                "have": int(player["coins"])}
    database.adjust_player_coins(user_id, -config.DUNGEON_ENTRY_COST)
    vitality = character.effective_stats(player)["vitality"]
    max_hp = config.DUNGEON_BASE_HP + vitality * config.DUNGEON_HP_PER_VITALITY
    database.create_dungeon_run(user_id, max_hp)
    return {"status": "entered", "run": database.get_active_dungeon_run(user_id)}


def advance(user_id, rng=random):
    """Спуститься глубже. Возвращает исход шага."""
    run = database.get_active_dungeon_run(user_id)
    if run is None:
        return {"status": "no_run"}

    depth = run["depth"] + 1
    hp, coins, treasures = run["hp"], run["coins_earned"], run["treasures"]

    if rng.random() < config.DUNGEON_TRAP_CHANCE:
        damage = config.DUNGEON_DAMAGE_PER_DEPTH * depth + rng.randint(0, depth * 2)
        hp -= damage
        if hp <= 0:
            database.finish_dungeon_run(run["id"], "dead")
            return {"status": "dead", "depth": depth, "damage": damage}
        database.update_dungeon_run(run["id"], depth, hp, coins, treasures)
        return {"status": "trap", "depth": depth, "hp": hp, "max_hp": run["max_hp"],
                "damage": damage, "coins": coins, "treasures": treasures}

    gain = config.DUNGEON_COINS_PER_DEPTH * depth
    coins += gain
    treasures += 1
    database.update_dungeon_run(run["id"], depth, hp, coins, treasures)
    return {"status": "treasure", "depth": depth, "hp": hp, "max_hp": run["max_hp"],
            "gain": gain, "coins": coins, "treasures": treasures}


def leave(user_id, rng=random):
    """Уйти с добычей. Начисляет монеты, лут и опыт. Возвращает сводку или ``None``."""
    run = database.get_active_dungeon_run(user_id)
    if run is None or not database.finish_dungeon_run(run["id"], "left"):
        return None

    database.adjust_player_coins(user_id, run["coins_earned"])
    player = database.get_or_create_player(user_id)
    luck = character.effective_stats(player)["luck"]

    items = []
    for _ in range(run["treasures"]):
        item = loot.generate(luck=luck, zone_bonus=0.1 * run["depth"], rng=rng)
        database.add_item(user_id, item)
        items.append(item)

    exp_info = character.grant_exp(user_id, config.DUNGEON_EXP_PER_DEPTH * run["depth"])
    return {
        "coins": run["coins_earned"],
        "items": items,
        "depth": run["depth"],
        "level_up": exp_info["level_up"],
        "level": exp_info["level"],
    }
