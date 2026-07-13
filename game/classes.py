"""Классы персонажа и вычисление характеристик (чистые функции)."""
import config

_DEFAULT_WEIGHTS = {"strength": 1 / 3, "vitality": 1 / 3, "luck": 1 / 3}


def get_class(code):
    """Определение класса по коду или ``None``."""
    return config.CLASSES.get(code)


def class_name(code) -> str:
    """Отображаемое имя класса (с эмодзи) или заглушка, если класс не выбран."""
    cls = config.CLASSES.get(code)
    if not cls:
        return "❓ Класс не выбран"
    return f"{cls['emoji']} {cls['name']}"


def stats_for(level: int, klass) -> dict:
    """Характеристики персонажа: база + очки за уровни по весам класса."""
    points = max(0, level - 1) * config.POINTS_PER_LEVEL
    cls = config.CLASSES.get(klass)
    weights = cls["weights"] if cls else _DEFAULT_WEIGHTS
    return {
        stat: config.BASE_STAT + round(points * weights.get(stat, 0))
        for stat in config.STATS
    }
