#!/bin/bash
# Выключает автозапуск и останавливает бота, запущенного через launchd.
LABEL="ru.avito-iphone-bot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "Бот остановлен." || echo "Бот через автозапуск не работал."
rm -f "$PLIST"
echo "✅ Автозапуск выключен."
