"""Лут: роллы редкости и предметов, бонусы предметов (чистые функции)."""
import random

import config


def roll_rarity(luck=0, zone_bonus=0.0, rng=random) -> str:
    """Выбрать редкость. Удача и бонус зоны смещают шансы к редким тирам."""
    factor = 1 + luck * 0.02 + zone_bonus
    weights = [
        config.RARITIES[code][2] * (factor ** i)
        for i, code in enumerate(config.RARITY_ORDER)
    ]
    total = sum(weights)
    threshold = rng.random() * total
    acc = 0.0
    for code, w in zip(config.RARITY_ORDER, weights, strict=True):
        acc += w
        if threshold <= acc:
            return code
    return config.RARITY_ORDER[0]


def _templates_for_rarity(rarity):
    return [code for code, t in config.ITEM_TEMPLATES.items()
            if t["rarity"] == rarity]


def roll_item(luck=0, zone_bonus=0.0, rng=random) -> str:
    """Выбрать конкретный предмет (код шаблона) с учётом удачи и зоны."""
    rarity = roll_rarity(luck, zone_bonus, rng)
    # Спускаемся к ближайшей редкости, для которой есть предметы
    order = config.RARITY_ORDER
    idx = order.index(rarity)
    for i in range(idx, -1, -1):
        candidates = _templates_for_rarity(order[i])
        if candidates:
            return rng.choice(candidates)
    # Крайний случай — любой предмет
    return rng.choice(list(config.ITEM_TEMPLATES))


def item_bonus(template_code) -> dict:
    """Бонус предмета к характеристике его слота."""
    tmpl = config.ITEM_TEMPLATES.get(template_code)
    if not tmpl:
        return {}
    stat = config.SLOTS[tmpl["slot"]][2]
    mult = config.RARITIES[tmpl["rarity"]][3]
    return {stat: mult}


def item_label(template_code) -> str:
    """Читаемое название предмета с эмодзи редкости и слота."""
    tmpl = config.ITEM_TEMPLATES.get(template_code)
    if not tmpl:
        return "❓ Неизвестный предмет"
    rarity_emoji = config.RARITIES[tmpl["rarity"]][0]
    slot_emoji = config.SLOTS[tmpl["slot"]][0]
    return f"{rarity_emoji} {slot_emoji} {tmpl['name']}"
