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
- **«⬅️ Меню» после действий**: ЛЮБОЙ edit персонального экрана (результат
  экспедиции, комната/смерть подземелья, перерисовка магазина/фермы/инвентаря)
  обязан приложить `_with_back(markup, user_id)` — иначе игрок в тупике.
  Исключение — ОБЩИЕ артефакты (вызов/результат дуэли, авто-карточка босса,
  `link_stats`): туда back не ставить, чтобы один игрок не «увёл» общий экран.

## Двухэтажное меню (антифлуд + не пугать новичков)
- Инлайн `@bot` → статья «🎮 Меню» → `open_menu` → `cmd_menu` (главный этаж:
  только классика `MAIN_MENU` + кнопка «🎮 RPG ▸» = `nav_{owner}_rpg`).
- `cmd_rpg` — второй этаж (`RPG_MENU`: профиль/экспедиции/боссы/…). Вся сложность
  спрятана сюда, чтобы пришедший поржать видел 6 кнопок, а не 15.
- `_nav` рендерит экран через `_screen()`; кнопка «назад» контекстная:
  RPG-экраны (`RPG_SCREENS`) → назад в `rpg`, классика → в `menu`. Экран `menu`
  без back, `rpg` → назад в `menu`. `_with_back(markup, owner, dest="rpg"|"menu")`.
- `/menu` в группе — тот же главный хаб. Легаси `cmd_{screen}` — `_run_command`.
- Тексты: жёсткий тон/дотерский жаргон в контенте; статы/интерфейс — ясные.
  Пояснения (что делает стат и т.п.) — только в экране «info», не на экранах.

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
| `boss_hit` / `boss_hit_{owner}` | `_boss_hit` | удар по user_id нажавшего; вариант с owner — карточка в чьём-то меню (сохраняет «⬅️ Меню» при перерисовке), без owner — общая карточка чата (авто-спавн) |
| `dng_enter_{code}` / `dng_deep_{owner}` / `dng_fight_{owner}` / `dng_flee_{owner}` / `dng_leave_{owner}` | `_dungeon_*` | выбор, спуск, бой/побег от моба, выход |
| `buy_chest_{code}` / `shop_reclass` / `reclass_{owner}_{code}` | `_buy_chest`/`_shop_reclass`/`_reclass` | магазин |
| `convert_{cm}` | `_convert_cm` | обмен см→монеты |
| `sell_{item_id}` / `sellall_{rarity}` | `_sell_item`/`_sell_all` | продажа (ownership в SQL) |
| `craft_menu` / `craft_{rarity}` | `_craft_menu`/`_craft` | крафт тира выше |
| `claim_income` / `upgrade_prop` | `_claim_income`/`_upgrade_prop` | ферма |
| `link_stats` | inline в handle_button | активация чата (связка уже сделана `_chat_key`) |

## Таблицы SQLite (fairdick.db)
- `user_sizes` (user_id, chat_id, size, max_size, grow_streak, last_grow_date…) — чатовый размер
- `grow_history` — лог grow (топ недели); `dick_of_day`; `duel_stats`
- `active_duels` (duel_id, status: active/completed/expired, bet, inline_message_id)
- `chats` (chat_id, is_active) — куда бот добавлен; `chat_links` (chat_instance→chat_id)
- `players` (user_id PK, exp, level, klass, coins, property_level, income_at) — глобальный персонаж
- `player_items` (id, user_id, template, rarity, slot, stats JSON, equipped)
- `expeditions` (user_id, zone, chat_key, ends_at, status: active/claimed)
- `bosses` (chat_key, hp, status: active/defeated) + `boss_hits` (boss_id, user_id, damage, last_hit_at)
- `dungeon_runs` (user_id, dungeon, depth, hp, coins_earned, treasures, room JSON-моб, status: active/left/dead)
- `achievements` (user_id, chat_id, code)

Миграции: только ADD COLUMN/CREATE TABLE IF NOT EXISTS в `init_db()`. Путь к БД —
env `DATABASE_PATH` (тесты подменяют + `importlib.reload(config, database)`).

## Игровые формулы (все константы в config.py)
- **5 характеристик**: strength (дуэли/босс), vitality (HP подземелья), luck (лут),
  crit (удвоение урона босса), speed (ускорение экспедиций). **5 слотов** 1:1:
  weapon→str, helmet→crit, armor→vit, boots→speed, artifact→luck.
- Уровень: шаг `LEVEL_STEP*L`; статы: `BASE_STAT + POINTS_PER_LEVEL*(level-1)`
  по весам класса (класс качает только str/vit/luck) + бонусы предметов.
- **Предмет — экземпляр** `{template, rarity, slot, stats}`; stats роллятся при
  выпадении (`loot.generate`) и хранятся в `player_items.stats` (JSON). Статы
  СЛУЧАЙНЫЕ: число (`ITEM_STAT_COUNT`) и бюджет (`ITEM_STAT_BUDGET`) зависят от
  редкости, какие статы и как делится бюджет — рандом (слот на статы не влияет,
  оставлен как косметика). `loot.item_bonus(row)` — из JSON, фолбэк на осн. стат
  слота для легаси-предметов.
- **Длина = статус + сила**: `utils.title_for(size)` — титул по длине (`config.TITLES`);
  длина даёт +урон по боссу (`BOSS_DAMAGE_PER_CM`) и сдвиг шанса дуэли
  (`DUEL_CM_PER_PERCENT`). Титул в шапке меню/профиля/топа.
- Лут: веса редкостей × factor^i, **factor = 1 + LUCK_RARITY_FACTOR·√luck +
  zone_bonus, кап RARITY_FACTOR_CAP** (затухание — иначе Удача раздувает верх).
  Веса верхних тиров намеренно низкие (эпик+ ≈3-6%), чтобы редкое было редким.
- Подземелья (`config.DUNGEONS`, 5 шт., гейтинг по уровню): каждый шаг — комната
  по весам `DUNGEON_ROOM_WEIGHTS` (моб 40% / сокровище 30% / ловушка 20% /
  привал 10%). Моб хранится в `dungeon_runs.room` (JSON) — пока он там, deeper и
  leave заблокированы (только fight/flee). Бой в один клик (`dungeon.fight`):
  Сила+Крит бьют, Скорость = уклон (`DUNGEON_DODGE_*`), Живучесть = HP; побег
  (`flee`) не убивает (min 1 HP). Награды рандомные (диапазоны + прирост за
  глубину), EV растёт по тирам ТОЛЬКО при соответствующем гире (симуляция:
  слабак в высоком тире уходит в минус). `loot_floor` — минимум редкости лута.
- Дроп босса — ОТДЕЛЬНАЯ таблица (`loot.generate_floored`): пол редкости по доле
  урона (`BOSS_LOOT_FLOORS`: ≥40%→легендарка, ≥20%→эпик, ≥8%→редкое),
  топ-дамагеру шанс `BOSS_TOP_TIER_UP_CHANCE` на +1 тир. Босс всегда жирнее
  сундуков/подземелий.
- Дуэль: шанс = 0.5 + 0.02*(power_a - power_b), кламп 0.35..0.65; power = strength+level.
- Босс: урон = BOSS_BASE_DAMAGE + strength + rand(0..strength), крит (шанс
  `crit*BOSS_CRIT_PER_POINT`, кап) удваивает; награды по вкладу урона.
- Экспедиция: длительность × (1 − min(cap, speed·SPEED_PER_POINT)).
- Ферма: rate*часы, кап `PROPERTY_CAP_HOURS`; улучшение сначала собирает доход.
- Экономика: продажа `SELL_PRICES[rarity]`; обмен `CM_PER_COIN` см = 1 монета
  (односторонний); казино — на монеты; крафт: `CRAFT_ITEMS_REQUIRED` предметов
  тира → 1 тира выше (самые старые ненадетые, `consume_items_for_craft`).

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
