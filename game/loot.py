"""Лут: роллы редкости и предметов, бонусы и оформление (чистые функции).

Предмет — это экземпляр: ``{template, rarity, slot, stats}``. Характеристики
роллятся в момент выпадения и хранятся у экземпляра (в БД — JSON), поэтому два
одинаковых по шаблону предмета могут отличаться вторичными статами.
"""
import json
import math
import random

import config


def _rarity_factor(luck, zone_bonus) -> float:
    """Множитель редкости: 1 + вклад Удачи (со своим капом) + бонус зоны.

    Вклад Удачи капается ОТДЕЛЬНО (``LUCK_BOOST_CAP``), поэтому на дорогих
    сундуках с высоким ``zone_bonus`` Удача продолжает двигать ролл вверх,
    а не упирается в общий потолок. Итог ограничен ``RARITY_FACTOR_CAP``.
    """
    luck_boost = min(config.LUCK_BOOST_CAP,
                     config.LUCK_RARITY_FACTOR * math.sqrt(max(0, luck)))
    return min(1 + luck_boost + zone_bonus, config.RARITY_FACTOR_CAP)


def roll_rarity(luck=0, zone_bonus=0.0, rng=random) -> str:
    """Выбрать редкость. Вклад Удачи затухает (sqrt) и ограничен капом."""
    factor = _rarity_factor(luck, zone_bonus)
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


def roll_rarity_floored(floor, luck=0, zone_bonus=0.0, rng=random) -> str:
    """Ролл редкости не ниже ``floor``: веса тиров ниже пола отбрасываются.

    Используется для дропа с боссов и лут-фло подземелий: гарантирует минимум
    и оставляет шанс на тиры выше (Удача и бонус двигают вверх).
    """
    order = config.RARITY_ORDER
    start = order.index(floor) if floor in order else 0
    factor = _rarity_factor(luck, zone_bonus)
    codes = order[start:]
    weights = [config.RARITIES[c][2] * (factor ** i) for i, c in enumerate(codes)]
    total = sum(weights)
    threshold = rng.random() * total
    acc = 0.0
    for code, w in zip(codes, weights, strict=True):
        acc += w
        if threshold <= acc:
            return code
    return codes[0]


def generate_floored(floor, luck=0, zone_bonus=0.0, rng=random) -> dict:
    """Сгенерировать экземпляр с гарантированным минимумом редкости."""
    rarity = roll_rarity_floored(floor, luck, zone_bonus, rng)
    return _instance(_pick_template(rarity, rng), rng)


def _templates_for_rarity(rarity):
    return [code for code, t in config.ITEM_TEMPLATES.items()
            if t["rarity"] == rarity]


def _pick_template(rarity, rng=random):
    """Шаблон нужной редкости; при отсутствии — спускаемся к более частой."""
    order = config.RARITY_ORDER
    for i in range(order.index(rarity), -1, -1):
        candidates = _templates_for_rarity(order[i])
        if candidates:
            return rng.choice(candidates)
    return rng.choice(list(config.ITEM_TEMPLATES))


def build_item_stats(slot, rarity, rng=random) -> dict:
    """Характеристики экземпляра: случайные статы + бюджет очков по редкости.

    Число статов и бюджет зависят от редкости; какие именно статы и как делится
    бюджет — случайно. ``slot`` не влияет на статы (оставлен для совместимости).
    """
    lo, hi = config.ITEM_STAT_COUNT[rarity]
    pool = list(config.STATS)
    count = min(rng.randint(lo, hi), len(pool))
    chosen = rng.sample(pool, count)
    budget = config.ITEM_STAT_BUDGET[rarity]
    stats = {stat: 1 for stat in chosen}          # каждому минимум 1
    for _ in range(max(0, budget - count)):        # остаток раскидываем случайно
        stats[rng.choice(chosen)] += 1
    return stats


def generate(luck=0, zone_bonus=0.0, rng=random) -> dict:
    """Сгенерировать экземпляр предмета с учётом Удачи и бонуса зоны."""
    rarity = roll_rarity(luck, zone_bonus, rng)
    template = _pick_template(rarity, rng)
    return _instance(template, rng)


def generate_of_rarity(rarity, rng=random) -> dict:
    """Сгенерировать экземпляр конкретной редкости (для крафта)."""
    return _instance(_pick_template(rarity, rng), rng)


def _instance(template, rng):
    tmpl = config.ITEM_TEMPLATES[template]
    return {
        "template": template,
        "rarity": tmpl["rarity"],
        "slot": tmpl["slot"],
        "stats": build_item_stats(tmpl["slot"], tmpl["rarity"], rng),
    }


def item_bonus(item_row) -> dict:
    """Характеристики экземпляра из строки БД (с фолбэком для старых предметов)."""
    raw = item_row.get("stats") if isinstance(item_row, dict) else None
    if raw:
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            pass
    # Легаси: у старого предмета stats нет — считаем только основной стат
    tmpl = config.ITEM_TEMPLATES.get(item_row.get("template"))
    if not tmpl:
        return {}
    return {config.SLOTS[tmpl["slot"]][2]: config.RARITIES[tmpl["rarity"]][3]}


def stats_text(stats: dict) -> str:
    """Компактная строка бонусов: «💪 +8  💥 +3»."""
    parts = []
    for stat, (emoji, _name, _desc) in config.STATS.items():
        if stats.get(stat):
            parts.append(f"{emoji} +{stats[stat]}")
    return "  ".join(parts)


def item_label(template_code) -> str:
    """Название предмета с эмодзи редкости и слота."""
    tmpl = config.ITEM_TEMPLATES.get(template_code)
    if not tmpl:
        return "❓ Неизвестный предмет"
    rarity_emoji = config.RARITIES[tmpl["rarity"]][0]
    slot_emoji = config.SLOTS[tmpl["slot"]][0]
    return f"{rarity_emoji} {slot_emoji} {tmpl['name']}"
