"""Подземелья: push-your-luck забег.

Несколько подземелий с гейтингом по уровню. Игрок платит за вход и спускается
глубже. На каждом шаге — либо ловушка (урон, растёт с глубиной), либо комната
(монеты; предмет — НЕ гарантированно, по ``item_chance``). Риск ловушки растёт
с глубиной, поэтому бесконечно фармить нельзя. Можно уйти с добычей или погибнуть
и потерять всё (включая плату за вход).
"""
import random

import config
import database
from game import character, loot


def get_dungeon(code):
    return config.DUNGEONS.get(code)


def _run_dungeon(run):
    """Параметры подземелья забега (с фолбэком на первое — для старых записей)."""
    return config.DUNGEONS.get(run["dungeon"]) or next(iter(config.DUNGEONS.values()))


def available_dungeons(level):
    """Список (code, dungeon, unlocked) по уровню игрока."""
    return [
        (code, d, level >= d["min_level"])
        for code, d in config.DUNGEONS.items()
    ]


def enter(user_id, dungeon_code):
    """Войти в подземелье. Возвращает словарь с исходом (см. ``status``)."""
    dungeon = config.DUNGEONS.get(dungeon_code)
    if dungeon is None:
        return {"status": "bad"}
    if database.get_active_dungeon_run(user_id) is not None:
        return {"status": "in_run", "run": database.get_active_dungeon_run(user_id)}
    player = database.get_or_create_player(user_id)
    if player["level"] < dungeon["min_level"]:
        return {"status": "low_level", "need": dungeon["min_level"]}
    if player["coins"] < dungeon["entry_cost"]:
        return {"status": "no_coins", "need": dungeon["entry_cost"],
                "have": int(player["coins"])}
    database.adjust_player_coins(user_id, -dungeon["entry_cost"])
    vitality = character.effective_stats(player)["vitality"]
    max_hp = config.DUNGEON_BASE_HP + vitality * config.DUNGEON_HP_PER_VITALITY
    database.create_dungeon_run(user_id, dungeon_code, max_hp)
    return {"status": "entered", "run": database.get_active_dungeon_run(user_id)}


def trap_chance(dungeon, depth):
    """Шанс ловушки на данной глубине (растёт с глубиной, с капом)."""
    return min(dungeon["trap_cap"],
               dungeon["trap_chance"] + dungeon["trap_growth"] * depth)


def advance(user_id, rng=random):
    """Спуститься глубже. Возвращает исход шага."""
    run = database.get_active_dungeon_run(user_id)
    if run is None:
        return {"status": "no_run"}
    dungeon = _run_dungeon(run)

    depth = run["depth"] + 1
    hp, coins, treasures = run["hp"], run["coins_earned"], run["treasures"]

    if rng.random() < trap_chance(dungeon, depth):
        damage = (dungeon["damage_base"] + dungeon["damage_per_depth"] * depth
                  + rng.randint(0, depth))
        hp -= damage
        if hp <= 0:
            database.finish_dungeon_run(run["id"], "dead")
            return {"status": "dead", "depth": depth, "damage": damage}
        database.update_dungeon_run(run["id"], depth, hp, coins, treasures)
        return {"status": "trap", "depth": depth, "hp": hp, "max_hp": run["max_hp"],
                "damage": damage, "coins": coins, "treasures": treasures}

    gain = dungeon["coins_per_depth"] * depth
    coins += gain
    found_item = rng.random() < dungeon["item_chance"]
    if found_item:
        treasures += 1
    database.update_dungeon_run(run["id"], depth, hp, coins, treasures)
    return {"status": "treasure", "depth": depth, "hp": hp, "max_hp": run["max_hp"],
            "gain": gain, "coins": coins, "treasures": treasures,
            "found_item": found_item}


def leave(user_id, rng=random):
    """Уйти с добычей. Начисляет монеты, лут и опыт. Возвращает сводку или ``None``."""
    run = database.get_active_dungeon_run(user_id)
    if run is None or not database.finish_dungeon_run(run["id"], "left"):
        return None
    dungeon = _run_dungeon(run)

    database.adjust_player_coins(user_id, run["coins_earned"])
    player = database.get_or_create_player(user_id)
    luck = character.effective_stats(player)["luck"]

    items = []
    for _ in range(run["treasures"]):
        item = loot.generate(luck=luck, zone_bonus=dungeon["loot_bonus"], rng=rng)
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
