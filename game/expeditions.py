"""Экспедиции: отправка героя в зону и получение наград.

Модель «ленивых событий»: экспедиция хранит время возвращения ``ends_at``.
Награда выдаётся, когда игрок её забирает (или когда срабатывает уведомление),
а не по таймеру — это надёжнее и переживает перезапуски бота.
"""
import random
from datetime import timedelta

import config
import database
import utils
from game import character, loot


def get_zone(code):
    return config.ZONES.get(code)


def available_zones(level):
    """Список (code, zone, unlocked) — открыта ли зона на данном уровне."""
    return [
        (code, zone, level >= zone["min_level"])
        for code, zone in config.ZONES.items()
    ]


def is_ready(expedition) -> bool:
    """Вернулась ли экспедиция (наступило время)."""
    return utils.now() >= _parse(expedition["ends_at"])


def time_left(expedition) -> timedelta:
    """Сколько осталось до возвращения (может быть отрицательным)."""
    return _parse(expedition["ends_at"]) - utils.now()


def start(user_id, zone_code, chat_key):
    """Отправить героя в экспедицию.

    Возвращает ``(expedition_id, ends_at)`` либо строку с причиной отказа.
    """
    zone = config.ZONES.get(zone_code)
    if zone is None:
        return "Неизвестная зона."
    player = database.get_or_create_player(user_id)
    if player["level"] < zone["min_level"]:
        return f"Нужен уровень {zone['min_level']} для этой зоны."
    if database.get_active_expedition(user_id) is not None:
        return "Твой герой уже в экспедиции!"
    duration = effective_duration(player, zone)
    ends_at = (utils.now() + timedelta(seconds=duration)).isoformat()
    expedition_id = database.create_expedition(user_id, zone_code, chat_key, ends_at)
    return expedition_id, ends_at


def effective_duration(player, zone) -> int:
    """Длительность зоны с учётом Скорости героя (ускорение с капом)."""
    speed = character.effective_stats(player)["speed"]
    reduction = min(config.EXPEDITION_SPEED_CAP,
                    speed * config.EXPEDITION_SPEED_PER_POINT)
    return int(zone["duration"] * (1 - reduction))


def claim(user_id, rng=random):
    """Забрать награду за завершённую экспедицию.

    Возвращает словарь с наградой, либо ``None`` (нет готовой экспедиции).
    """
    expedition = database.get_active_expedition(user_id)
    if expedition is None or not is_ready(expedition):
        return None
    claimed = database.claim_expedition(expedition["id"])
    if claimed is None:
        return None  # кто-то уже забрал (гонка с уведомлением)

    zone = config.ZONES[claimed["zone"]]
    player = database.get_or_create_player(user_id)
    luck = character.effective_stats(player)["luck"]

    coins = rng.randint(*zone["coins"])
    database.adjust_player_coins(user_id, coins)
    exp_info = character.grant_exp(user_id, zone["exp"])

    item = loot.generate(luck=luck, zone_bonus=zone["luck_bonus"], rng=rng)
    database.add_item(user_id, item)

    return {
        "zone": zone,
        "coins": coins,
        "exp": zone["exp"],
        "level_up": exp_info["level_up"],
        "level": exp_info["level"],
        "item": item,
        "chat_key": claimed["chat_key"],
    }


def _parse(ts):
    from datetime import datetime
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=utils.TZ)
    return dt
