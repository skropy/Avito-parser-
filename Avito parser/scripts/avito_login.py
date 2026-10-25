"""Открывает браузер бота, чтобы вы один раз вручную вошли в рабочий аккаунт Авито.
    ./venv/bin/python scripts/avito_login.py
Войдите в аккаунт, затем просто закройте окно браузера — сессия сохранится в data/browser_profile.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.avito.browser import AvitoBrowser  # noqa: E402
from bot.config import Config  # noqa: E402


async def main() -> None:
    browser = AvitoBrowser(Config())
    await browser.start()
    await browser.page.goto("https://www.avito.ru/#login?authsrc=h")
    print("Окно браузера открыто. Войдите в рабочий аккаунт Авито (телефон + код из SMS).")
    print("Когда увидите своё имя в правом верхнем углу — закройте окно браузера.")
    try:
        while any(not p.is_closed() for p in browser.context.pages):
            await asyncio.sleep(1)
    except Exception:
        pass
    await browser.stop()
    print("✅ Готово, вход сохранён.")


if __name__ == "__main__":
    asyncio.run(main())
