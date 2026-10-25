"""Проверка, что бот правильно читает Авито (ничего не отправляет).
    ./venv/bin/python scripts/check_avito.py
Открывает поиск из config.yaml, показывает первые объявления и разбирает
одну карточку. Если поля пустые — значит, Авито поменял вёрстку и нужно
поправить bot/avito/selectors.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.avito.browser import AvitoBlocked, AvitoBrowser  # noqa: E402
from bot.avito.listing import fetch_listing  # noqa: E402
from bot.avito.search import fetch_search  # noqa: E402
from bot.config import Config  # noqa: E402
from bot.pricing.model_parser import memory_label, parse_listing  # noqa: E402
from bot.pricing.sheet import PriceTable  # noqa: E402

MARKERS_JS = "[...new Set([...document.querySelectorAll('[data-marker]')].map(e => e.dataset.marker))]"


async def main() -> None:
    cfg = Config()
    prices = PriceTable(cfg)
    try:
        await prices.refresh()
    except Exception as e:
        print("Таблица цен не загрузилась:", e)
    browser = AvitoBrowser(cfg)
    await browser.start()
    try:
        while True:
            try:
                items = await fetch_search(browser, cfg.get("search.search_url"))
                break
            except AvitoBlocked as e:
                input(f"Авито показывает {e.kind}. Пройдите её в окне браузера и нажмите Enter здесь… ")
        print(f"\nНа странице поиска найдено объявлений: {len(items)}")
        for it in items[:10]:
            pr = parse_listing(it.title, "", prices.matcher)
            model = f"{prices.models.get(pr.model_key, '?')} {memory_label(pr.memory)}" if pr.model_key else pr.reason
            print(f"  {it.id} | {it.price} ₽ | {it.title[:60]} → {model}")
        if not items:
            markers = await browser.page.evaluate(MARKERS_JS)
            print("data-marker на странице:", markers[:80])
            return
        print("\nРазбираю карточку:", items[0].url)
        data = await fetch_listing(browser, items[0].url)
        for k, v in data.items():
            if k == "description":
                v = (v or "")[:150] + "…"
            print(f"  {k}: {v}")
        empty = [k for k in ("title", "price", "description", "seller_name", "seller_reviews") if not data.get(k) and data.get(k) != 0]
        if empty:
            print("\n!!! Не прочитались поля:", ", ".join(empty))
            markers = await browser.page.evaluate(MARKERS_JS)
            print("data-marker на странице карточки:", markers[:120])
        else:
            print("\n✅ Основные поля читаются.")
        input("\nНажмите Enter, чтобы закрыть браузер… ")
    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
