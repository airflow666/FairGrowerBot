"""Боссы чата: общий HP-пул, удары по кулдауну, дроп по вкладу урона."""
import random
from datetime import datetime

import config
import database
import utils
from game import character, loot


def summon(chat_key):
    """Показать активного босса или заспавнить нового.

    Возвращает ``(boss, is_new)``.
    """
    existing = database.get_active_boss(chat_key)
    if existing:
        return existing, False
    tmpl = random.choice(config.BOSS_TEMPLATES)
    database.spawn_boss(chat_key, tmpl["name"], tmpl["emoji"], tmpl["hp"])
    return database.get_active_boss(chat_key), True


def cooldown_left(boss_id, user_id) -> float:
    """Сколько секунд осталось до следующего удара игрока (0 — можно бить)."""
    hit = database.get_boss_hit(boss_id, user_id)
    if not hit or not hit["last_hit_at"]:
        return 0.0
    last = datetime.fromisoformat(hit["last_hit_at"])
    if last.tzinfo is None:
        last = last.replace(tzinfo=utils.TZ)
    elapsed = (utils.now() - last).total_seconds()
    return max(0.0, config.BOSS_HIT_COOLDOWN - elapsed)


def hit(user_id, chat_key, rng=random):
    """Ударить босса. Возвращает словарь с исходом (см. поле ``status``)."""
    boss = database.get_active_boss(chat_key)
    if boss is None:
        return {"status": "no_boss"}

    cd = cooldown_left(boss["id"], user_id)
    if cd > 0:
        return {"status": "cooldown", "left": cd}

    player = database.get_or_create_player(user_id)
    stats = character.effective_stats(player)
    strength = stats["strength"]
    # Длина имеет значение: +1 урона за каждые BOSS_DAMAGE_PER_CM см (чатовой)
    length_bonus = database.get_user_size(user_id, chat_key) // config.BOSS_DAMAGE_PER_CM
    damage = config.BOSS_BASE_DAMAGE + strength + length_bonus + rng.randint(0, strength)
    crit = rng.random() < min(config.BOSS_CRIT_CAP,
                              stats["crit"] * config.BOSS_CRIT_PER_POINT)
    if crit:
        damage *= 2

    new_hp = database.apply_boss_hit(boss["id"], user_id, damage)
    if new_hp <= 0:
        if database.defeat_boss(boss["id"]):
            rewards = _distribute_rewards(boss, rng)
            return {"status": "killed", "boss": boss, "damage": damage,
                    "crit": crit, "rewards": rewards}
        return {"status": "no_boss"}  # кто-то добил раньше
    return {"status": "hit", "boss": boss, "damage": damage, "crit": crit,
            "hp": new_hp, "max_hp": boss["max_hp"]}


def loot_floor_for_share(share) -> str:
    """Гарантированный минимум редкости дропа по доле нанесённого урона."""
    for threshold, rarity in config.BOSS_LOOT_FLOORS:
        if share >= threshold:
            return rarity
    return config.BOSS_LOOT_FLOORS[-1][1]


def _bump_rarity(rarity) -> str:
    """Поднять редкость на один тир (с потолком)."""
    order = config.RARITY_ORDER
    idx = order.index(rarity)
    return order[min(idx + 1, len(order) - 1)]


def _distribute_rewards(boss, rng):
    """Раздать монеты, опыт и лут по вкладу урона.

    Дроп босса — отдельная таблица: пол редкости зависит от доли урона
    (больше вложился — гарантированно лучше лут), топ-дамагер с шансом
    получает пол ещё на тир выше.
    """
    contributors = database.get_boss_contributors(boss["id"])
    total = sum(c["damage"] for c in contributors) or 1
    results = []
    for i, c in enumerate(contributors):
        uid = c["user_id"]
        player = database.get_or_create_player(uid)  # гарантируем запись до начислений
        coins = round(config.BOSS_COIN_POOL * c["damage"] / total)
        database.adjust_player_coins(uid, coins)
        character.grant_exp(uid, config.BOSS_EXP_REWARD)

        share = c["damage"] / total
        floor = loot_floor_for_share(share)
        if i == 0 and rng.random() < config.BOSS_TOP_TIER_UP_CHANCE:
            floor = _bump_rarity(floor)
        luck = character.effective_stats(player)["luck"]
        item = loot.generate_floored(floor, luck=luck, rng=rng)
        database.add_item(uid, item)

        results.append({
            "user_id": uid, "coins": coins, "damage": c["damage"],
            "item": item, "top": i == 0,
        })
    return results
