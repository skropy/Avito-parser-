"""Проверка настроек: Telegram и таблица цен.
    ./venv/bin/python scripts/check_setup.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.config import Config  # noqa: E402
from bot.pricing.model_parser import memory_label  # noqa: E402
from bot.pricing.sheet import PriceTable  # noqa: E402


async def main() -> int:
    ok = True
    cfg = Config()
    print("1) config.yaml прочитан. Режим:", "DRY RUN (продавцам не пишет)" if cfg.dry_run else "БОЕВОЙ")

    print("2) Telegram…")
    if not cfg.telegram_token or not cfg.telegram_chat_id:
        print("   !!! в .env не заполнены TELEGRAM_BOT_TOKEN и/или TELEGRAM_CHAT_ID")
        ok = False
    else:
        from aiogram import Bot
        bot = Bot(cfg.telegram_token)
        try:
            me = await bot.get_me()
            await bot.send_message(cfg.telegram_chat_id, "✅ Проверка связи: бот видит ваш чат.")
            print(f"   ок — бот @{me.username}, тестовое сообщение отправлено, проверьте Telegram")
        except Exception as e:
            print("   !!! ошибка:", e)
            ok = False
        finally:
            await bot.session.close()

    print("3) Таблица цен…")
    prices = PriceTable(cfg)
    try:
        await prices.refresh()
        print(f"   ок — источник: {prices.source}, строк: {len(prices.rows)}")
        for (key, mem), row in list(prices.rows.items())[:5]:
            print(f"     {row.model} {memory_label(mem)}: скупка {row.buy}, продажа {row.sell}")
        if len(prices.rows) > 5:
            print("     …")
        if not cfg.google_sheet_id:
            print("   (GOOGLE_SHEET_ID пустой — используются цены из prices_example.csv)")
    except Exception as e:
        print("   !!! ошибка:", e)
        ok = False

    print("\n✅ Всё в порядке" if ok else "\n!!! Есть проблемы — см. выше и README, раздел «Если что-то не работает»")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
