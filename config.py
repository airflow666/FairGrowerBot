# Конфигурация бота
import os

from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Имя бота для упоминаний (опционально)
BOT_USERNAME = os.getenv("BOT_USERNAME", "@FairDickGrowerBot")

# Путь к файлу базы данных (можно переопределить через переменную окружения)
DATABASE_PATH = os.getenv("DATABASE_PATH", "fairdick.db")

# Часовой пояс, по которому считаются "сутки" для grow и писюна дня
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Ограничения для команды grow (включительно)
GROW_MIN = -10
GROW_MAX = 35

# Ограничения для бонуса "писюн дня"
DICK_OF_DAY_MIN = 1
DICK_OF_DAY_MAX = 30

# Дуэль: доступные ставки и время жизни вызова (в секундах)
DUEL_STAKES = [1, 2, 3, 4, 5]
DUEL_TIMEOUT = 120

# Казино: доступные ставки и множитель выигрыша
CASINO_STAKES = [1, 2, 3, 5, 10]
CASINO_WIN_MULTIPLIER = 2

# --- RPG: персонаж, опыт, классы ---------------------------------------------

# Опыт за действия
EXP_PER_GROW = 10
EXP_PER_DUEL_WIN = 15
EXP_PER_DUEL_LOSS = 5

# Кривая уровней: опыт для перехода с уровня L на L+1 = LEVEL_STEP * L
LEVEL_STEP = 100

# Характеристики: база в каждой + очки за уровень, распределяемые по классу
BASE_STAT = 5
POINTS_PER_LEVEL = 3

# Дуэль: шанс победы = 0.5 + PER_POWER * (сила_атакующего - сила_защитника),
# ограниченный коридором [MIN, MAX], чтобы новичков нельзя было фармить
DUEL_CHANCE_MIN = 0.35
DUEL_CHANCE_MAX = 0.65
DUEL_CHANCE_PER_POWER = 0.02

# Классы: code -> параметры. weights — распределение очков характеристик.
CLASSES = {
    "giga": {
        "emoji": "💪",
        "name": "Гигачад",
        "desc": "Мастер дуэлей — упор в Силу.",
        "perk": "Сильнее в дуэлях",
        "weights": {"strength": 0.6, "vitality": 0.2, "luck": 0.2},
    },
    "lucky": {
        "emoji": "🍀",
        "name": "Везунчик",
        "desc": "Любимец фортуны — упор в Удачу.",
        "perk": "Лучше редкий лут (в экспедициях)",
        "weights": {"strength": 0.2, "vitality": 0.2, "luck": 0.6},
    },
    "tank": {
        "emoji": "🛡️",
        "name": "Танк",
        "desc": "Живучий боец — упор в Живучесть.",
        "perk": "Больше HP (в боях с боссами)",
        "weights": {"strength": 0.2, "vitality": 0.6, "luck": 0.2},
    },
}

# Характеристики для отображения: code -> (эмодзи, название)
STATS = {
    "strength": ("💪", "Сила"),
    "vitality": ("🛡️", "Живучесть"),
    "luck": ("🍀", "Удача"),
}

# --- RPG: редкости, предметы, зоны -------------------------------------------

# Редкости: code -> (эмодзи, название, вес в лут-таблице, множитель бонуса)
# Порядок важен (от обычного к реликтовому) — используется в лут-роллах.
RARITIES = {
    "common":    ("⚪", "Обычный",     45.0, 1),
    "uncommon":  ("🟢", "Необычный",   27.0, 2),
    "rare":      ("🔵", "Редкий",      15.0, 3),
    "epic":      ("🟣", "Эпический",    8.0, 5),
    "legendary": ("🟠", "Легендарный",  3.5, 8),
    "mythic":    ("🔴", "Мифический",   1.2, 12),
    "relic":     ("🌟", "Реликтовый",   0.3, 18),
}

# Слоты экипировки: code -> (эмодзи, название, усиливаемая характеристика)
SLOTS = {
    "weapon":   ("⚔️", "Оружие", "strength"),
    "armor":    ("🛡️", "Броня", "vitality"),
    "artifact": ("💍", "Артефакт", "luck"),
}

# Названия предметов: slot -> rarity -> [названия]. Из них строится каталог.
_ITEM_NAMES = {
    "weapon": {
        "common": ["Ржавый меч", "Деревянная дубина"],
        "uncommon": ["Стальной клинок"],
        "rare": ["Гномья секира"],
        "epic": ["Клинок бури"],
        "legendary": ["Драконобой"],
        "mythic": ["Коса Жнеца"],
        "relic": ["Экскалибур"],
    },
    "armor": {
        "common": ["Кожаный жилет", "Тряпьё"],
        "uncommon": ["Кольчуга"],
        "rare": ["Латы стража"],
        "epic": ["Броня титана"],
        "legendary": ["Панцирь дракона"],
        "mythic": ["Доспех бессмертных"],
        "relic": ["Эгида богов"],
    },
    "artifact": {
        "common": ["Кроличья лапка", "Медный амулет"],
        "uncommon": ["Кольцо удачи"],
        "rare": ["Око фортуны"],
        "epic": ["Талисман судьбы"],
        "legendary": ["Звезда удачи"],
        "mythic": ["Слеза феникса"],
        "relic": ["Грааль"],
    },
}


def _build_item_templates():
    """Каталог предметов: code -> {name, slot, rarity}. Коды стабильны."""
    catalog = {}
    for slot, by_rarity in _ITEM_NAMES.items():
        for rarity, names in by_rarity.items():
            for i, name in enumerate(names):
                catalog[f"{slot}_{rarity}_{i}"] = {
                    "name": name, "slot": slot, "rarity": rarity,
                }
    return catalog


ITEM_TEMPLATES = _build_item_templates()

# Зоны экспедиций: code -> параметры. duration — в секундах.
ZONES = {
    "meadow": {
        "emoji": "🌾", "name": "Цветущий луг", "min_level": 1,
        "duration": 3600, "exp": 20, "coins": (5, 15), "luck_bonus": 0.0,
    },
    "forest": {
        "emoji": "🌲", "name": "Тёмный лес", "min_level": 3,
        "duration": 4 * 3600, "exp": 60, "coins": (20, 50), "luck_bonus": 0.1,
    },
    "caves": {
        "emoji": "🕳️", "name": "Глубокие пещеры", "min_level": 6,
        "duration": 8 * 3600, "exp": 150, "coins": (60, 120), "luck_bonus": 0.25,
    },
}

# Порядок редкостей от обычного к реликтовому (для лут-роллов)
RARITY_ORDER = list(RARITIES.keys())

# Максимум предметов в инвентаре для показа (чтобы не раздувать сообщение)
INVENTORY_DISPLAY_LIMIT = 20


# Достижения: code -> (эмодзи, название)
ACHIEVEMENTS = {
    "first_grow": ("🌱", "Первый росток"),
    "size_50": ("📏", "Полметра"),
    "size_100": ("🍆", "Легенда чата (100 см)"),
    "jackpot": ("🎰", "Джекпот (+35 за раз)"),
    "unlucky": ("💀", "Не повезло (-10 за раз)"),
    "streak_7": ("🔥", "Неделя подряд"),
    "duel_win_1": ("⚔️", "Первая победа в дуэли"),
    "duel_win_10": ("👑", "Дуэлянт (10 побед)"),
    "dick_of_day": ("🎉", "Писюн дня"),
}
