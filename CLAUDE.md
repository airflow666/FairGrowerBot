# CLAUDE.md — карта проекта FairGrowerBot

Telegram-бот: чатовая игра (grow/топы/дуэли/казино) + RPG-слой (персонаж,
экспедиции, боссы, подземелья, экономика). Python 3.11+, python-telegram-bot 22,
SQLite. План развития — `ROADMAP.md` (этапы 0–5 сделаны, 6 — впереди).

## Запуск и проверки
```bash
. .venv/bin/activate            # локальная венва (в .gitignore)
ruff check .                    # линт — должен быть чистым
pytest -q                       # тесты на изолированной tmp-БД, без токена
python main.py                  # запуск (нужен BOT_TOKEN в .env)
```
CI: `.github/workflows/ci.yml` (ruff + pytest). Деплой: `deploy/upgrade.sh`
(бэкап БД → стоп → pull → deps → миграция → старт), systemd — `deploy/install-service.sh`.

## Модули
| Файл | Ответственность |
|---|---|
| `main.py` | Регистрация всех хендлеров/команд, JobQueue-расписание (полночь — писюн дня; 18:00 — спавн боссов), error handler |
| `handlers.py` | ВСЕ callback-кнопки (`handle_button` — единый диспетчер по префиксу), inline-меню, функции экранов `cmd_*` (канало-независимые: возвращают text или (text, markup)) |
| `group.py` | Групповой режим: `/команды` (тонкие обёртки над `handlers.cmd_*`), `on_my_chat_member` (добавление в чат → приветствие), авто-джобы (`auto_dick_of_day`, `spawn_bosses`) |
| `database.py` | Вся персистентность. `_connect()` контекст-менеджер (WAL, commit/close), `init_db()` — схема + миграции `_ensure_column` |
| `game/` | Чистая игровая логика, БЕЗ Telegram: `leveling` `classes` `character` `loot` `expeditions` `boss` `dungeon` `economy` |
| `config.py` | ВСЕ числа баланса и каталоги (классы, редкости, предметы, зоны, боссы, магазин, ферма) |
| `utils.py` | `now()/today_str()` (TZ из конфига), `format_mention` (HTML-escape имён!) |

## Ключевые концепции
- **chat_key** — идентификатор чата, строка. Либо `str(chat.id)` (бот в группе),
  либо `chat_instance` (inline). Связка и перенос данных: `link_chat_instance()`;
  `resolve_chat_key()` маппит instance→chat_id. `_chat_key(query)` в handlers
  линкует автоматически при нажатии кнопки под обычным сообщением.
- **Гибридные профили**: чатовое (ключ user_id+chat_key): user_sizes, duel_stats,
  dick_of_day, achievements, grow_history. Глобальное (ключ user_id): players
  (exp/level/klass/coins/ферма), player_items, expeditions, dungeon_runs.
- **Ленивые события**: экспедиции/доход фермы считаются в момент забора
  (сравнение с `ends_at`/`income_at`), таймеры не обязательны. JobQueue-посты —
  best-effort надстройка.
- **Атомарность**: гонки решаются guarded UPDATE + rowcount: `apply_grow`
  (раз в день), `claim_duel`, `claim_expedition`, `defeat_boss`,
  `finish_dungeon_run`. Паттерн: UPDATE ... WHERE status='active' → rowcount==0
  значит «уже занято».
- **Ответ на callback — РОВНО ОДИН РАЗ** (Telegram игнорирует повторные и попап
  теряется). Только через `_answer(query, text, alert=)` — НИКОГДА не звать
  `query.answer()` напрямую и не отвечать «заранее». `handle_button` в finally
  гасит спиннер fallback-ответом (безопасно: повторный глотается).
- **Антифлуд**: экраны редактируют то же сообщение; результаты действий —
  попапом (`_answer(..., alert=True)`); единое меню (см. ниже). Инлайн-сообщения
  удалить нельзя — только редактировать.
- **Владелец меню**: кнопки с данными игрока зашивают owner_id в callback_data
  (`nav_{owner}_{screen}`, `setclass_{owner}_{code}`, `dng_deep_{owner}`,
  `reclass_{owner}_{code}`); чужое нажатие → попап-отказ.

## Единое меню (антифлуд-UX)
- Инлайн `@bot` → одна статья «🎮 Меню» → кнопка `open_menu` (первый нажавший —
  владелец) → хаб `cmd_menu` с кнопками `nav_{owner}_{screen}`.
- `/menu` в группе — тот же хаб от автора команды.
- `_nav` рендерит экран через реестр `_screen()` и добавляет `_with_back()`
  (кнопка «⬅️ Меню»). Экран «menu» — без back.
- Легаси `cmd_{screen}` колбэки старых сообщений работают через `_run_command`.

## Реестр callback_data (handle_button)
| Префикс/значение | Обработчик | Заметки |
|---|---|---|
| `nav_{owner}_{screen}` | `_nav` | навигация меню, owner-guard |
| `open_menu` | inline | первый нажавший становится владельцем |
| `cmd_{screen}` | `_run_command` | легаси-кнопки старых сообщений |
| `create_duel_{bet}` | `_create_duel` | превращает сообщение в вызов |
| `accept_duel_{duel_id}` | `_accept_duel` | проверки ДО claim; затем атомарный claim |
| `casino_{bet}` | `_play_casino` | попап-результат + панель остаётся |
| `setclass_{owner}_{code}` | `_set_class` | первый выбор класса (бесплатно) |
| `start_exp_{zone}` | `_start_expedition` | + job возврата, если чат активный |
| `claim_exp` | `_claim_expedition` | по user_id нажавшего |
| `equip_{item_id}` | `_equip_item` | ownership проверяется в SQL |
| `boss_hit` | `_boss_hit` | по user_id нажавшего, кулдаун в boss_hits |
| `dng_enter` / `dng_deep_{owner}` / `dng_leave_{owner}` | `_dungeon_*` | push-your-luck |
| `buy_chest_{code}` / `shop_reclass` / `reclass_{owner}_{code}` | `_buy_chest`/`_shop_reclass`/`_reclass` | магазин |
| `claim_income` / `upgrade_prop` | `_claim_income`/`_upgrade_prop` | ферма |
| `link_stats` | inline в handle_button | активация чата (связка уже сделана `_chat_key`) |

## Таблицы SQLite (fairdick.db)
- `user_sizes` (user_id, chat_id, size, max_size, grow_streak, last_grow_date…) — чатовый размер
- `grow_history` — лог grow (топ недели); `dick_of_day`; `duel_stats`
- `active_duels` (duel_id, status: active/completed/expired, bet, inline_message_id)
- `chats` (chat_id, is_active) — куда бот добавлен; `chat_links` (chat_instance→chat_id)
- `players` (user_id PK, exp, level, klass, coins, property_level, income_at) — глобальный персонаж
- `player_items` (id, user_id, template, rarity, slot, equipped)
- `expeditions` (user_id, zone, chat_key, ends_at, status: active/claimed)
- `bosses` (chat_key, hp, status: active/defeated) + `boss_hits` (boss_id, user_id, damage, last_hit_at)
- `dungeon_runs` (user_id, depth, hp, coins_earned, treasures, status: active/left/dead)
- `achievements` (user_id, chat_id, code)

Миграции: только ADD COLUMN/CREATE TABLE IF NOT EXISTS в `init_db()`. Путь к БД —
env `DATABASE_PATH` (тесты подменяют + `importlib.reload(config, database)`).

## Игровые формулы (все константы в config.py)
- Уровень: шаг `LEVEL_STEP*L`; статы: `BASE_STAT + POINTS_PER_LEVEL*(level-1)`
  по весам класса + бонусы надетых предметов (`character.effective_stats`).
- Дуэль: шанс = 0.5 + 0.02*(power_a - power_b), кламп 0.35..0.65; power = strength+level.
- Лут: веса редкостей × factor^i, factor = 1 + luck*0.02 + zone_bonus (`loot.roll_rarity`).
- Босс: урон = BOSS_BASE_DAMAGE + strength + rand(0..strength); награды по вкладу.
- Ферма: rate*часы, кап `PROPERTY_CAP_HOURS`; улучшение сначала собирает доход.

## Грабли (не наступать повторно)
1. `ChosenInlineResult` НЕ имеет chat_id — не использовать (см. ROADMAP).
2. Ответ на callback один раз — только `_answer` (см. выше). Реальный Telegram
   бросает на повторный answer; фейки в тестах должны эмулировать это.
3. Инлайн-сообщение нельзя удалить и у его callback нет `query.message`.
4. `edit_message_text` с тем же текстом → BadRequest «message is not modified»
   (казино оборачивает в try/except).
5. Имена пользователей — только через `format_mention` (HTML-инъекция).
6. В группах privacy mode: бот видит только /команды, не обычные сообщения.
7. Проверки принятия дуэли — ДО `claim_duel`, иначе вызов «сжигается».

## Тесты (tests/)
`test_database` (grow/дуэли/связка чатов), `test_game` (уровни/классы/шансы),
`test_expeditions` (лут/зоны/экипировка), `test_boss`, `test_dungeon`,
`test_economy`, `test_utils`. Фикстуры: tmp-БД через env + reload. RNG
инжектится параметром `rng=` (детерминизм).

## Процесс
Ветка: `claude/telegram-bot-review-t9wd42`. После мержа PR пользователем —
новый PR для следующей порции (смёрженный не переиспользовать). Пуш:
`git push -u origin <ветка>` с ретраями. Перед коммитом: ruff + pytest + smoke.
