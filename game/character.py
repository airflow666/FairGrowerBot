"""Операции над персонажем: опыт, класс, характеристики, шансы дуэли."""
import config
import database
from game import classes, leveling, loot


def get_or_create(user_id, username=None, first_name=None) -> dict:
    """Получить (или создать) глобального персонажа игрока."""
    return database.get_or_create_player(user_id, username, first_name)


def grant_exp(user_id, amount, username=None, first_name=None) -> dict:
    """Начислить опыт. Возвращает информацию о начислении и повышении уровня."""
    player = database.get_or_create_player(user_id, username, first_name)
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


def effective_stats(player: dict) -> dict:
    """Характеристики персонажа: класс/уровень + бонусы надетых предметов."""
    stats = classes.stats_for(player["level"], player["klass"])
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
