# Конфигурация бота
import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Имя бота для упоминаний
BOT_USERNAME = os.getenv("BOT_USERNAME", "@FairDickGrowerBot")

# Часовой пояс МСК (UTC+3)
MSK_TIMEZONE = "Europe/Moscow"

# Ограничения для команды grow
GROW_MIN = -10  # Минимальное значение
GROW_MAX = 35   # Максимальное значение

# Ограничения для dick of the day
DICK_OF_DAY_MIN = 1
DICK_OF_DAY_MAX = 30

# Ограничения для кредита (пока не используется)
CREDIT_MAX = 20

# Минимальная ставка для дуэли
DUEL_MIN_BET = 1
