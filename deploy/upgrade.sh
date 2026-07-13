#!/usr/bin/env bash
#
# Безопасное обновление FairGrowerBot на сервере с сохранением базы данных.
#
# Что делает:
#   1. Делает бэкап базы (файл .db и WAL-файлы, если есть)
#   2. Останавливает бота (systemd-сервис или процесс python main.py)
#   3. Обновляет код из git (текущая ветка или указанная аргументом)
#   4. Ставит зависимости (в venv, если он есть)
#   5. Прогоняет миграцию БД и проверяет, что данные не потерялись
#   6. Запускает бота обратно
#   7. При ошибке до успешной миграции — восстанавливает базу из бэкапа
#
# Использование:
#   ./deploy/upgrade.sh [ветка]
#
# Переменные окружения (необязательные):
#   SERVICE=имя-systemd-сервиса   — если автоопределение не сработало
#   BRANCH=имя-ветки              — то же, что аргумент
#
# Скрипт целиком обёрнут в функцию main(), чтобы bash дочитал его в память
# до того, как git обновит файл на диске.

set -euo pipefail

main() {
    # --- Настройки и пути ---------------------------------------------------
    local script_dir repo_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    repo_dir="$(cd "$script_dir/.." && pwd)"
    cd "$repo_dir"

    if [[ ! -f main.py || ! -f database.py ]]; then
        echo "ОШИБКА: запусти скрипт из репозитория бота (не нашёл main.py)." >&2
        exit 1
    fi
    if ! git rev-parse --git-dir >/dev/null 2>&1; then
        echo "ОШИБКА: это не git-репозиторий." >&2
        exit 1
    fi

    local branch
    branch="${1:-${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}}"

    # Путь к базе: из .env (DATABASE_PATH) либо значение по умолчанию
    local db_path="fairdick.db"
    if [[ -f .env ]]; then
        local from_env
        from_env="$(grep -E '^[[:space:]]*DATABASE_PATH=' .env | tail -n1 | cut -d= -f2- || true)"
        # Убираем CR, ведущие/хвостовые пробелы и обрамляющие кавычки
        from_env="$(printf '%s' "$from_env" | sed -e 's/\r$//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^["'\'']//' -e 's/["'\'']$//')"
        [[ -n "$from_env" ]] && db_path="$from_env"
    fi

    # Интерпретатор: venv, если найден, иначе системный python3
    local py pip_cmd
    if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
        py="$VIRTUAL_ENV/bin/python"
    elif [[ -x "$repo_dir/venv/bin/python" ]]; then
        py="$repo_dir/venv/bin/python"
    elif [[ -x "$repo_dir/.venv/bin/python" ]]; then
        py="$repo_dir/.venv/bin/python"
    else
        py="$(command -v python3 || command -v python)"
    fi
    pip_cmd="$py -m pip"

    echo "==> Репозиторий : $repo_dir"
    echo "==> Ветка       : $branch"
    echo "==> База данных : $db_path"
    echo "==> Python      : $py"
    echo

    # --- Бэкап базы ---------------------------------------------------------
    local backup=""
    local migrated_ok=0
    if [[ -f "$db_path" ]]; then
        backup="${db_path}.bak-$(date +%F-%H%M%S)"
        cp -p "$db_path" "$backup"
        # WAL/SHM тоже копируем, если есть (на случай незакоммиченных страниц)
        [[ -f "${db_path}-wal" ]] && cp -p "${db_path}-wal" "${backup}-wal"
        [[ -f "${db_path}-shm" ]] && cp -p "${db_path}-shm" "${backup}-shm"
        echo "==> Бэкап базы создан: $backup"
    else
        echo "==> Базы $db_path пока нет — будет создана заново (нечего терять)."
    fi

    # Откат базы при аварии до успешной миграции
    rollback() {
        local code=$?
        if [[ $migrated_ok -eq 0 && -n "$backup" && -f "$backup" ]]; then
            echo
            echo "!!! Сбой (код $code). Восстанавливаю базу из бэкапа..." >&2
            cp -p "$backup" "$db_path"
            [[ -f "${backup}-wal" ]] && cp -p "${backup}-wal" "${db_path}-wal"
            [[ -f "${backup}-shm" ]] && cp -p "${backup}-shm" "${db_path}-shm"
            echo "!!! База восстановлена. Код НЕ откачен — при желании: git checkout <прежний-коммит>" >&2
        fi
    }
    trap rollback ERR

    # --- Определяем и останавливаем бота ------------------------------------
    local service="${SERVICE:-}"
    if [[ -z "$service" ]]; then
        service="$(detect_service "$repo_dir")"
    fi

    if [[ -n "$service" ]]; then
        echo "==> Останавливаю systemd-сервис: $service"
        sudo systemctl stop "$service"
    else
        stop_process "$repo_dir"
    fi

    # --- Обновляем код ------------------------------------------------------
    echo "==> Обновляю код (git fetch + checkout $branch)"
    git fetch origin "$branch"
    git checkout "$branch"
    git pull --ff-only origin "$branch"

    # --- Зависимости --------------------------------------------------------
    echo "==> Устанавливаю зависимости"
    $pip_cmd install --quiet --upgrade pip >/dev/null 2>&1 || true
    $pip_cmd install --quiet -r requirements.txt

    # --- Миграция и проверка целостности ------------------------------------
    local before_users=0
    if [[ -n "$backup" ]]; then
        before_users="$(count_users "$py" "$backup")"
    fi

    echo "==> Выполняю миграцию базы"
    DATABASE_PATH="$db_path" "$py" -c "import database; database.init_db()"

    local after_users
    after_users="$(count_users "$py" "$db_path")"
    echo "==> Пользователей в базе: было $before_users, стало $after_users"
    if (( after_users < before_users )); then
        echo "ОШИБКА: после миграции стало меньше записей — прерываю." >&2
        exit 1
    fi

    migrated_ok=1  # дальше базу не трогаем, откат отключён
    trap - ERR

    # --- Запускаем бота -----------------------------------------------------
    if [[ -n "$service" ]]; then
        echo "==> Запускаю сервис: $service"
        sudo systemctl start "$service"
        sleep 2
        sudo systemctl --no-pager --lines=10 status "$service" || true
    else
        echo "==> Запускаю бота в фоне (nohup), лог: $repo_dir/bot.log"
        nohup "$py" main.py >>"$repo_dir/bot.log" 2>&1 &
        sleep 2
        echo "    PID: $!"
        echo "    Последние строки лога:"
        tail -n 15 "$repo_dir/bot.log" 2>/dev/null || true
    fi

    echo
    echo "✅ Готово. Бэкап базы: ${backup:-（не создавался）}"
    echo "   Проверь бота в Telegram (Grow/Top/Stats — старые размеры на месте)."
}

# Число строк в user_sizes (0, если таблицы/файла нет)
count_users() {
    local py="$1" db="$2"
    "$py" - "$db" <<'PY'
import sqlite3, sys
try:
    c = sqlite3.connect(sys.argv[1])
    print(c.execute("SELECT COUNT(*) FROM user_sizes").fetchone()[0])
except Exception:
    print(0)
PY
}

# Автоопределение systemd-сервиса, чей ExecStart ссылается на этот каталог
detect_service() {
    local repo_dir="$1" unit
    command -v systemctl >/dev/null 2>&1 || { echo ""; return; }
    for unit in $(systemctl list-units --type=service --state=running --no-legend 2>/dev/null | awk '{print $1}'); do
        if systemctl show "$unit" -p ExecStart -p WorkingDirectory 2>/dev/null | grep -qF "$repo_dir"; then
            echo "${unit%.service}"
            return
        fi
    done
    echo ""
}

# Это именно наш бот? Интерпретатор python, аргумент main.py, cwd = каталог бота.
# Строгая проверка, чтобы не убить постороннюю оболочку/редактор, где просто
# встречается строка "main.py".
is_bot_process() {
    local pid="$1" repo_dir="$2"
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && return 1   # не трогаем себя
    [[ -r "/proc/$pid/cmdline" ]] || return 1
    local args=() exe_ok=0 main_ok=0 a
    mapfile -d '' -t args < "/proc/$pid/cmdline" 2>/dev/null || return 1
    [[ "$(basename "${args[0]:-}")" == python* ]] && exe_ok=1
    for a in "${args[@]}"; do
        [[ "$(basename "$a")" == "main.py" ]] && main_ok=1
    done
    (( exe_ok && main_ok )) || return 1
    [[ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" == "$repo_dir" ]]
}

# Остановка процесса python main.py, запущенного из этого каталога
stop_process() {
    local repo_dir="$1" pid found=0
    for pid in $(pgrep -f 'main\.py' 2>/dev/null || true); do
        if is_bot_process "$pid" "$repo_dir"; then
            echo "==> Останавливаю процесс бота (PID $pid)"
            kill "$pid" 2>/dev/null || true
            found=1
        fi
    done
    if [[ $found -eq 1 ]]; then
        sleep 2
        # Добить, если ещё жив
        for pid in $(pgrep -f 'main\.py' 2>/dev/null || true); do
            is_bot_process "$pid" "$repo_dir" && kill -9 "$pid" 2>/dev/null || true
        done
    else
        echo "==> Запущенный процесс бота не найден (возможно, уже остановлен)."
    fi
}

main "$@"
