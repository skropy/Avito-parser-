#!/bin/bash
# Запуск бота. caffeinate -i не даёт Mac уснуть, пока бот работает.
cd "$(dirname "$0")/.."
exec /usr/bin/caffeinate -i ./venv/bin/python main.py
