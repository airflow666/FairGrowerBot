#!/usr/bin/env bash
#
# Установка systemd-сервиса для FairGrowerBot.
#
# Подставляет в шаблон fairdickbot.service реального пользователя, путь к
# репозиторию и интерпретатор Python (venv, если найден), затем ставит юнит,
# включает автозапуск и запускает бота.
#
# Использование (нужен sudo):
#   sudo ./deploy/install-service.sh
#
# Переменные окружения (необязательные):
#   SERVICE_NAME=имя      — имя сервиса (по умолчанию fairdickbot)
#   RUN_USER=пользователь — от кого запускать (по умолчанию вызвавший sudo)

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
template="$script_dir/fairdickbot.service"

service_name="${SERVICE_NAME:-fairdickbot}"
run_user="${RUN_USER:-${SUDO_USER:-$(id -un)}}"

if [[ ! -f "$template" ]]; then
    echo "ОШИБКА: не найден шаблон $template" >&2
    exit 1
fi
if [[ ! -f "$repo_dir/main.py" ]]; then
    echo "ОШИБКА: $repo_dir не похож на репозиторий бота (нет main.py)" >&2
    exit 1
fi
if [[ "$(id -u)" -ne 0 ]]; then
    echo "ОШИБКА: запусти через sudo (нужны права на /etc/systemd/system)." >&2
    exit 1
fi

# Интерпретатор: venv, если есть, иначе системный python3
if [[ -x "$repo_dir/venv/bin/python" ]]; then
    python_bin="$repo_dir/venv/bin/python"
elif [[ -x "$repo_dir/.venv/bin/python" ]]; then
    python_bin="$repo_dir/.venv/bin/python"
else
    python_bin="$(command -v python3)"
fi

target="/etc/systemd/system/${service_name}.service"

echo "==> Сервис        : $service_name"
echo "==> Пользователь  : $run_user"
echo "==> Рабочая папка : $repo_dir"
echo "==> Python        : $python_bin"
echo "==> Юнит          : $target"

# Рендерим шаблон (| как разделитель sed — в путях нет этого символа)
rendered="$(sed \
    -e "s|__USER__|$run_user|g" \
    -e "s|__WORKDIR__|$repo_dir|g" \
    -e "s|__PYTHON__|$python_bin|g" \
    "$template")"

printf '%s\n' "$rendered" > "$target"

systemctl daemon-reload
systemctl enable "$service_name"
systemctl restart "$service_name"
sleep 2
systemctl --no-pager --lines=15 status "$service_name" || true

echo
echo "✅ Сервис установлен и запущен."
echo "   Логи:      journalctl -u $service_name -f"
echo "   Рестарт:   sudo systemctl restart $service_name"
echo "   Остановка: sudo systemctl stop $service_name"
