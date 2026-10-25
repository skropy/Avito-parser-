"""Узнать свой chat_id: напишите своему боту любое сообщение и запустите
    ./venv/bin/python scripts/get_chat_id.py
"""
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    print("!!! Сначала впишите TELEGRAM_BOT_TOKEN в файл .env")
    sys.exit(1)

try:
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    ctx = ssl.create_default_context()

with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", context=ctx, timeout=20) as r:
    data = json.load(r)

if not data.get("ok"):
    print("!!! Telegram ответил ошибкой — проверьте токен:", data)
    sys.exit(1)

chats = {}
for upd in data.get("result", []):
    msg = upd.get("message") or upd.get("edited_message") or {}
    chat = msg.get("chat")
    if chat:
        name = chat.get("username") or chat.get("first_name") or chat.get("title") or ""
        chats[chat["id"]] = name

if not chats:
    print("Сообщений не найдено. Откройте своего бота в Telegram, нажмите «Старт» или напишите ему")
    print("любое слово, подождите 5 секунд и запустите этот скрипт ещё раз.")
    sys.exit(1)

for cid, name in chats.items():
    print(f"chat_id: {cid}   ({name})")
print("\nВпишите это число в .env:  TELEGRAM_CHAT_ID=<число>")
