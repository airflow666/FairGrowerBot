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
