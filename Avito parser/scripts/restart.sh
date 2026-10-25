#!/bin/bash
# Перезапуск бота, работающего через автозапуск (например, после правки .env).
LABEL="ru.avito-iphone-bot"
launchctl kickstart -k "gui/$(id -u)/$LABEL" && echo "✅ Бот перезапущен." \
  || echo "!!! Автозапуск не включён. Включить: ./scripts/install_autostart.sh"
