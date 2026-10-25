#!/bin/bash
# Включает автозапуск бота через launchd: бот стартует при входе в macOS
# и перезапускается, если упал.
set -e
cd "$(dirname "$0")/.."
PROJECT_DIR="$(pwd)"
LABEL="ru.avito-iphone-bot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "$PROJECT_DIR" in
  "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*)
    echo "!!! Папка проекта лежит в «Документах», на «Рабочем столе» или в «Загрузках»:"
    echo "    $PROJECT_DIR"
    echo "    macOS не пускает туда автозапуск. Перенесите папку в домашнюю папку"
    echo "    (например, $HOME/avito-iphone-bot) — см. README, шаг 1."
    exit 1
    ;;
esac

if [ ! -x venv/bin/python ]; then
  echo "!!! Сначала выполните установку: ./scripts/setup.sh"
  exit 1
fi

chmod +x scripts/run.sh
mkdir -p "$HOME/Library/LaunchAgents" logs

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$PROJECT_DIR/scripts/run.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>LimitLoadToSessionType</key>
    <string>Aqua</string>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "✅ Автозапуск включён. Бот уже запускается (появится окно браузера)."
echo "   Файл: $PLIST"
echo "   Выключить: ./scripts/uninstall_autostart.sh"
