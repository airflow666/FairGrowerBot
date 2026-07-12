# FairDickGrowerBot — Контекст проекта

## Описание
Telegram-бот для дружеских соревнований в чатах. Вызывается через **@username_бота** (inline-режим). Не нужно добавлять в группу!

## Как работает
1. Пользователь пишет `@username_бота` в любом чате
2. Появляется меню команд (Grow, Top, Топ недели, Dick Of Day, Stats, Duel, Casino)
3. При нажатии кнопки inline-сообщение обновляется результатом команды
4. Данные разделяются по чатам ключом `chat_key`

### Про chat_key (важно)
Бот НЕ состоит в группах, поэтому реального `chat.id` в inline-режиме нет.
`ChosenInlineResult` в Bot API вообще не содержит `chat_id` (прежняя версия
падала на `chosen.chat_id`). Ключом разделения служит `chat_instance` из
callback-запроса (для inline-сообщений) либо реальный `chat.id`, если бот
всё же добавлен в группу. Хранится как непрозрачный идентификатор (TEXT).

## Архитектура
- **main.py** — точка входа: логирование, InlineQueryHandler, CallbackQueryHandler, error handler
- **handlers.py** — inline-меню, диспетчер кнопок, команды, дуэли, казино, достижения, таймаут дуэли (JobQueue)
- **database.py** — SQLite: контекст-менеджер соединения, миграции, атомарные grow/дуэли. Таблицы: user_sizes, dick_of_day, duel_stats, active_duels, grow_history, achievements
- **utils.py** — часовой пояс (zoneinfo) и `format_mention` с экранированием HTML
- **config.py** — константы, список достижений, настройки дуэли/казино

## Команды
- **📈 Grow** — рост -10..+35 см, раз в сутки; ведёт серию дней подряд (атомарно)
- **🏆 Top** — топ-10 по размеру
- **📅 Топ недели** — топ по приросту за 7 дней (из grow_history)
- **🎉 Dick Of Day** — случайный участник получает +1..+30 см, раз в сутки
- **📊 Stats** — размер, рекорд, серия, победы/поражения/винрейт, число достижений
- **⚔️ Duel** — ставки 1–5 см, приём кнопкой (атомарно), таймаут 2 мин
- **🎰 Casino** — ставка 1–10 см, шанс 50% на ×2

## Ключевые решения
- Все пользовательские имена экранируются (`html.escape`) — защита от поломки разметки
- Размеры целочисленные (INTEGER)
- Grow и приём дуэли атомарны (guarded UPDATE + rowcount), защита от даблкликов и гонок
- Достижения: `INSERT OR IGNORE`, разблокировка возвращает «новизну»
- Часовой пояс через `TIMEZONE` (по умолчанию Europe/Moscow)
- Миграции существующих БД через `ALTER TABLE ADD COLUMN`

## Зависимости
- python-telegram-bot[job-queue] >= 22.7
- python-dotenv >= 1.0.0
- tzdata (для zoneinfo на минимальных системах)

## Разработка
```bash
pip install -r requirements-dev.txt
ruff check .
pytest -q
```

## Запуск
```bash
pip install -r requirements.txt
python main.py
```

## Важно
- Inline Mode включён в BotFather (Inline feedback НЕ требуется)
- Данные в SQLite (`DATABASE_PATH`, по умолчанию fairdick.db)
- Каждый чат независим

## Git
- Репозиторий: https://github.com/airflow666/FairGrowerBot
- `.env` и `*.db` исключены из Git
