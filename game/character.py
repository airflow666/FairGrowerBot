"""Операции над персонажем: опыт, класс, характеристики, прокачка, дуэли."""
import json

import config
import database
from game import classes, leveling, loot


def get_or_create(user_id, username=None, first_name=None) -> dict:
    """Получить (или создать) глобального персонажа игрока."""
    return database.get_or_create_player(user_id, username, first_name)


def passive(klass):
    """Пассивка класса: (эмодзи, название, описание) или None."""
    cls = config.CLASSES.get(klass)
    return cls.get("passive") if cls else None


def grant_exp(user_id, amount, username=None, first_name=None) -> dict:
    """Начислить опыт (пассивка «Душный Гринд» даёт +10%).

    Возвращает информацию о начислении и повышении уровня.
    """
    player = database.get_or_create_player(user_id, username, first_name)
    if player["klass"] == "avg":
        amount = round(amount * (1 + config.PASSIVE_XP_BONUS))
    old_level = player["level"]
    new_exp = player["exp"] + amount
    new_level = leveling.level_for_exp(new_exp)
    database.update_player_progress(user_id, new_exp, new_level)
    return {
        "gained": amount,
        "level": new_level,
        "level_up": new_level - old_level,
    }


def set_class(user_id, klass) -> bool:
    """Задать класс персонажу. True при успехе (класс существует)."""
    if klass not in config.CLASSES:
        return False
    database.get_or_create_player(user_id)
    database.set_player_class(user_id, klass)
    return True


def bonus_stats(player: dict) -> dict:
    """Вложенные игроком свободные очки: {stat: points}."""
    raw = player.get("bonus_stats")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {k: int(v) for k, v in data.items() if k in config.STATS}
    except (ValueError, TypeError):
        return {}


def free_points(player: dict) -> int:
    """Сколько свободных очков прокачки не потрачено."""
    earned = max(0, player["level"] - 1) * config.FREE_POINTS_PER_LEVEL
    spent = sum(bonus_stats(player).values())
    return max(0, earned - spent)


def train_stat(user_id, stat) -> dict:
    """Вложить 1 свободное очко в характеристику. См. ``status``."""
    if stat not in config.STATS:
        return {"status": "bad"}
    player = database.get_or_create_player(user_id)
    left = free_points(player)
    if left <= 0:
        return {"status": "no_points"}
    bonus = bonus_stats(player)
    bonus[stat] = bonus.get(stat, 0) + 1
    database.set_player_bonus_stats(user_id, json.dumps(bonus))
    return {"status": "ok", "stat": stat, "value": bonus[stat], "left": left - 1}


def effective_stats(player: dict) -> dict:
    """Характеристики: класс/уровень + свободные очки + надетые предметы."""
    stats = classes.stats_for(player["level"], player["klass"])
    for stat, val in bonus_stats(player).items():
        stats[stat] = stats.get(stat, 0) + val
    for item in database.get_equipped(player["user_id"]):
        for stat, val in loot.item_bonus(item).items():
            stats[stat] = stats.get(stat, 0) + val
    return stats


def stats_for_user(user_id) -> dict:
    """Итоговые характеристики игрока по его id."""
    return effective_stats(database.get_or_create_player(user_id))


def _combat_power(player: dict) -> int:
    """Боевая мощь для дуэлей: Сила + уровень."""
    return effective_stats(player)["strength"] + player["level"]


def duel_win_chance(challenger_id, accepter_id, chat_key) -> float:
    """Шанс победы вызвавшего дуэль: статы + длина, в коридоре [MIN, MAX]."""
    a = database.get_or_create_player(challenger_id)
    b = database.get_or_create_player(accepter_id)
    len_a = database.get_user_size(challenger_id, chat_key)
    len_b = database.get_user_size(accepter_id, chat_key)
    chance = (0.5
              + config.DUEL_CHANCE_PER_POWER * (_combat_power(a) - _combat_power(b))
              + 0.01 * (len_a - len_b) / config.DUEL_CM_PER_PERCENT)
    return max(config.DUEL_CHANCE_MIN, min(config.DUEL_CHANCE_MAX, chance))
