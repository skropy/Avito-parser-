#!/bin/bash
# Первичная установка: виртуальное окружение, библиотеки, браузер Chromium.
set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"

echo "=== Папка проекта: $PROJECT_DIR"

PY=""
for candidate in python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$(command -v "$candidate")"; break; fi
done
if [ -z "$PY" ]; then
  echo "!!! Python 3.12 не найден. Установите его с https://www.python.org/downloads/ (см. README, шаг 2)"
  exit 1
fi
echo "=== Python: $PY ($("$PY" --version))"

if [ ! -d venv ]; then
  echo "=== Создаю виртуальное окружение venv"
  "$PY" -m venv venv
fi

echo "=== Устанавливаю библиотеки (1–3 минуты)"
./venv/bin/python -m pip install --upgrade pip >/dev/null
./venv/bin/python -m pip install -r requirements.txt

echo "=== Скачиваю браузер Chromium для Playwright (~150 МБ)"
./venv/bin/python -m playwright install chromium

mkdir -p data logs credentials
if [ ! -f .env ]; then
  cp .env.example .env
  echo "=== Создан файл .env — заполните его (README, шаги 4–6)"
fi
chmod +x scripts/*.sh start.command 2>/dev/null || true

echo ""
echo "✅ Установка завершена."
