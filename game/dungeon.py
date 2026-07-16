"""Подземелья: push-your-luck по комнатам.

Каждый шаг вглубь — комната: моб (бой в один клик или побег), сокровище
(рандомные монеты + шанс лута), ловушка (урон) или привал (лечение).
В бою работают ВСЕ статы: Сила = урон, Крит = удвоение, Скорость = уклон,
Живучесть = запас HP, Удача = редкость лута. Смерть = теряешь всё.
"""
import json
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


def current_mob(run):
    """Моб текущей комнаты забега или ``None``."""
    if not run.get("room"):
        return None
    try:
        return json.loads(run["room"])
    except (ValueError, TypeError):
        return None


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


def _roll_room_type(rng):
    threshold = rng.random()
    acc = 0.0
    for room_type, weight in config.DUNGEON_ROOM_WEIGHTS:
        acc += weight
        if threshold <= acc:
            return room_type
    return config.DUNGEON_ROOM_WEIGHTS[-1][0]


def _spawn_mob(dungeon, depth, rng):
    emoji, name = rng.choice(dungeon["mobs"])
    hp = rng.randint(*dungeon["mob_hp"]) + dungeon["mob_hp_per_depth"] * depth
    power = rng.randint(*dungeon["mob_power"]) + dungeon["mob_power_per_depth"] * depth
    bounty = (rng.randint(*dungeon["mob_bounty"])
              + dungeon["mob_bounty_per_depth"] * depth)
    return {"emoji": emoji, "name": name, "hp": hp, "power": power, "bounty": bounty}


def advance(user_id, rng=random):
    """Спуститься глубже. Возвращает исход шага (см. ``status``)."""
    run = database.get_active_dungeon_run(user_id)
    if run is None:
        return {"status": "no_run"}
    mob = current_mob(run)
    if mob is not None:
        return {"status": "mob_pending", "mob": mob}
    dungeon = _run_dungeon(run)

    depth = run["depth"] + 1
    hp, coins, treasures = run["hp"], run["coins_earned"], run["treasures"]
    room = _roll_room_type(rng)

    if room == "mob":
        mob = _spawn_mob(dungeon, depth, rng)
        database.update_dungeon_run(run["id"], depth, hp, coins, treasures)
        database.set_dungeon_room(run["id"], json.dumps(mob))
        return {"status": "mob", "depth": depth, "mob": mob}

    if room == "trap":
        damage = dungeon["trap_damage"] + dungeon["trap_per_depth"] * depth \
            + rng.randint(0, depth)
        hp -= damage
        if hp <= 0:
            database.finish_dungeon_run(run["id"], "dead")
            return {"status": "dead", "depth": depth, "damage": damage,
                    "cause": "ловушка"}
        database.update_dungeon_run(run["id"], depth, hp, coins, treasures)
        return {"status": "trap", "depth": depth, "hp": hp, "damage": damage}

    if room == "rest":
        heal = rng.randint(*dungeon["rest_heal"])
        hp = min(run["max_hp"], hp + heal)
        database.update_dungeon_run(run["id"], depth, hp, coins, treasures)
        return {"status": "rest", "depth": depth, "hp": hp, "heal": heal}

    # Сокровище: рандомные монеты, шанс предмета
    gain = rng.randint(*dungeon["coins_room"]) + dungeon["coins_per_depth"] * depth
    coins += gain
    found_item = rng.random() < dungeon["item_chance"]
    if found_item:
        treasures += 1
    database.update_dungeon_run(run["id"], depth, hp, coins, treasures)
    return {"status": "treasure", "depth": depth, "hp": hp, "gain": gain,
            "found_item": found_item}


def fight(user_id, rng=random):
    """Разрешить бой с мобом текущей комнаты (в один клик).

    Раунды считаются внутри: Сила/Крит бьют моба, Скорость уклоняет от ответок.
    """
    run = database.get_active_dungeon_run(user_id)
    if run is None:
        return {"status": "no_run"}
    mob = current_mob(run)
    if mob is None:
        return {"status": "no_mob"}
    dungeon = _run_dungeon(run)

    stats = character.effective_stats(database.get_or_create_player(user_id))
    crit_p = min(config.BOSS_CRIT_CAP, stats["crit"] * config.BOSS_CRIT_PER_POINT)
    dodge_p = min(config.DUNGEON_DODGE_CAP,
                  stats["speed"] * config.DUNGEON_DODGE_PER_POINT)

    hp, mob_hp = run["hp"], mob["hp"]
    dealt = taken = crits = dodges = 0
    while mob_hp > 0 and hp > 0:
        dmg = stats["strength"] + rng.randint(0, max(1, stats["strength"] // 2))
        if rng.random() < crit_p:
            dmg *= 2
            crits += 1
        mob_hp -= dmg
        dealt += dmg
        if mob_hp <= 0:
            break
        if rng.random() < dodge_p:
            dodges += 1
            continue
        hit = mob["power"] + rng.randint(0, max(1, mob["power"] // 2))
        hp -= hit
        taken += hit

    if hp <= 0:
        database.finish_dungeon_run(run["id"], "dead")
        return {"status": "dead", "depth": run["depth"], "mob": mob,
                "damage": taken, "cause": f"{mob['emoji']} {mob['name']}"}

    coins = run["coins_earned"] + mob["bounty"]
    treasures = run["treasures"]
    found_item = rng.random() < dungeon["mob_item_chance"]
    if found_item:
        treasures += 1
    database.update_dungeon_run(run["id"], run["depth"], hp, coins, treasures)
    database.set_dungeon_room(run["id"], None)
    return {"status": "win", "mob": mob, "hp": hp, "taken": taken,
            "dealt": dealt, "crits": crits, "dodges": dodges,
            "bounty": mob["bounty"], "found_item": found_item}


def flee(user_id, rng=random):
    """Сбежать от моба: без награды, возможна царапина (не смертельная)."""
    run = database.get_active_dungeon_run(user_id)
    if run is None:
        return {"status": "no_run"}
    mob = current_mob(run)
    if mob is None:
        return {"status": "no_mob"}

    stats = character.effective_stats(database.get_or_create_player(user_id))
    dodge_p = min(config.DUNGEON_DODGE_CAP,
                  stats["speed"] * config.DUNGEON_DODGE_PER_POINT)
    damage = 0
    if rng.random() >= dodge_p:
        damage = int(mob["power"] * config.DUNGEON_FLEE_DAMAGE * rng.random())
    hp = max(1, run["hp"] - damage)  # побег не убивает
    database.update_dungeon_run(run["id"], run["depth"], hp,
                                run["coins_earned"], run["treasures"])
    database.set_dungeon_room(run["id"], None)
    return {"status": "fled", "mob": mob, "hp": hp, "damage": damage}


def leave(user_id, rng=random):
    """Уйти с добычей (нельзя, пока в комнате моб). Возвращает сводку или None."""
    run = database.get_active_dungeon_run(user_id)
    if run is None or current_mob(run) is not None:
        return None
    if not database.finish_dungeon_run(run["id"], "left"):
        return None
    dungeon = _run_dungeon(run)

    database.adjust_player_coins(user_id, run["coins_earned"])
    player = database.get_or_create_player(user_id)
    luck = character.effective_stats(player)["luck"]

    items = []
    for _ in range(run["treasures"]):
        item = loot.generate_floored(dungeon.get("loot_floor", "common"),
                                     luck=luck,
                                     zone_bonus=dungeon["loot_bonus"], rng=rng)
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
