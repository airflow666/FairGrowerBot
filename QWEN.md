# FairDickGrowerBot — Контекст проекта

## Описание
Telegram-бот для дружеских соревнований в чатах. Вызывается через **@username_бота** (inline-режим). Не нужно добавлять в группу!

## Как работает
1. Пользователь пишет `@username_бота` в любом чате
2. Пояжаются 5 кнопок: Grow, Top, Dick Of Day, Stats, Duel
3. При нажатии кнопки — inline-результат обновляется с результатом команды
4. Данные разделяются по чатам через реальный `chat_id` из `chosen_inline_result`

## Архитектура
- **main.py** — точка входа, регистрация обработчиков (InlineQueryHandler, ChosenInlineResultHandler, CallbackQueryHandler)
- **handlers.py** — inline_query, chosen_inline_result, handle_button, команды (cmd_grow, cmd_top, cmd_dickofday, cmd_stats, cmd_duel, accept_duel, create_duel)
- **database.py** — SQLite (fairdick.db), таблицы: user_sizes, duel_stats, active_duels, dick_of_day
- **config.py** — константы (GROW_MIN=-10, GROW_MAX=35, DICK_OF_DAY_MIN=1, DICK_OF_DAY_MAX=30)

## Команды
- **📈 Grow** — случайный рост от -10 до +35 см, раз в сутки (после 00:00 МСК)
- **🏆 Top** — топ-10 участников чата
- **🎉 Dick Of Day** — случайный участник получает бонус +1..+30 см, раз в сутки. При повторном вызове показывает кто уже выбран
- **📊 Stats** — статистика дуэлей (победы/поражения/суммарный выигрыш)
- **⚔️ Duel** — кнопки ставок (1, 2, 3, 4, 5 см), другой участник может принять кнопкой

## Ключевые решения
- `chat_id` получается через `chosen_inline_result.chosen.chat_id` — это реальный ID чата/группы
- Если `chosen_inline_result` не сработал, используется `query.chat_instance` или сохранённый `_user_chat_ids`
- Имена пользователей отображаются как `@username` или `[имя](tg://user?id=uid)` (HTML формат)
- При отрицательном балансе — сообщение "😢 Твоя пипися слишком короткая! Возвращайся позже 🍆"
- Дуэль: нельзя принять если у участника размер < ставки
- Писюн дня хранится в таблице `dick_of_day` с бонусом, old_size, new_size

## Зависимости
- python-telegram-bot >= 22.7
- python-dotenv >= 1.0.0

## Запуск
```bash
python -m pip install -r requirements.txt
python main.py
```

## Важно
- Inline Feedback включён в BotFather
- Inline Mode включён в BotFather
- Данные хранятся в fairdick.db (SQLite)
- Каждый чат независим (данные не пересекаются)

## Git
- Репозиторий: https://github.com/airflow666/FairGrowerBot
- Ветка: main
- `.env` и `*.db` исключены из Git (конфиденциальные данные)
