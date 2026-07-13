"""Кривая уровней и опыта (чистые функции)."""
import config


def exp_to_reach(level: int) -> int:
    """Суммарный опыт, нужный чтобы достичь уровня ``level`` (уровень 1 = 0).

    Шаг между уровнями L и L+1 равен ``LEVEL_STEP * L``, поэтому суммарный
    опыт до уровня L — это ``LEVEL_STEP * (1 + 2 + ... + (L-1))``.
    """
    if level <= 1:
        return 0
    n = level - 1
    return config.LEVEL_STEP * n * (n + 1) // 2


def level_for_exp(exp: int) -> int:
    """Уровень, соответствующий накопленному опыту."""
    level = 1
    while exp >= exp_to_reach(level + 1):
        level += 1
    return level


def progress(exp: int):
    """Прогресс внутри текущего уровня.

    Возвращает ``(level, exp_in_level, exp_needed_for_level)``.
    """
    level = level_for_exp(exp)
    cur = exp_to_reach(level)
    nxt = exp_to_reach(level + 1)
    return level, exp - cur, nxt - cur
