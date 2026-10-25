"""Сквозная проверка логики бота без браузера и без Telegram (всё подменено заглушками)."""
import asyncio
import os
from datetime import datetime

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:TEST_token_for_tests_only")
os.environ.setdefault("TELEGRAM_CHAT_ID", "1")

import bot.scheduler as sch  # noqa: E402
from bot.avito.messenger import ChatMessage  # noqa: E402
from bot.avito.search import SearchItem  # noqa: E402
from bot.config import Config  # noqa: E402
from bot.storage import Storage  # noqa: E402


class FakeTG:
    def __init__(self):
        self.sent = []

    async def send(self, text, kb=None, reply_to=None):
        self.sent.append(text)
        return [len(self.sent)]

    async def send_card(self, text, kb, photos=None):
        return await self.send(text, kb)

    async def send_file_photo(self, path, caption):
        await self.send(caption)


class FakeBrowser:
    def __init__(self):
        self.lock = asyncio.Lock()

    async def detect_block(self, page=None):
        return None

    async def screenshot(self, name="x.png"):
        return None


def card(item_id, title, price, **kw):
    d = dict(id=item_id, url=f"https://www.avito.ru/moskva/telefony/x_{item_id}", title=title, price=price,
             description="Отличное состояние, акб 90%", photos=[], address="", metro=["Тульская"],
             seller_name="Алексей", seller_id=f"s{item_id}", seller_type="private", seller_rating=4.9,
             seller_reviews=23, seller_active_listings=1, battery=90)
    d.update(kw)
    return d


def make_app(tmp_path, monkeypatch, dry_run=True, hour=12):
    cfg = Config()
    cfg.data["dry_run"] = dry_run
    cfg.data["messaging"]["send_pause_min_sec"] = 0
    cfg.data["messaging"]["send_pause_max_sec"] = 0
    app = sch.App(cfg)
    app.tg = FakeTG()
    app.browser = FakeBrowser()
    app.db = Storage(tmp_path / "bot.db", cfg.timezone)
    monkeypatch.setattr(app, "now", lambda: datetime(2026, 10, 25, hour, 0, tzinfo=app.tz))
    return app


def test_full_flow(tmp_path, monkeypatch):
    async def scenario():
        app = make_app(tmp_path, monkeypatch, dry_run=True)
        await app.db.open()
        await app.prices.refresh()

        search = [SearchItem("1", "u1", "iPhone 15 Pro 256", 60000, ""),
                  SearchItem("2", "u2", "iPhone 14 128", 30000, "")]
        cards = {}

        async def fake_search(browser, url):
            return search

        async def fake_listing(browser, url):
            return dict(cards[url])

        monkeypatch.setattr(sch, "fetch_search", fake_search)
        monkeypatch.setattr(sch, "fetch_listing", fake_listing)

        # 1. первый запуск — всё помечается просмотренным, без карточек
        await app.search_pass()
        assert "Первый запуск" in app.tg.sent[-1]
        assert app.queue.qsize() == 0

        # 2. новые объявления
        new = [
            ("10", "iPhone 15 Pro 256 ГБ", 60000, {}),                      # ✅ +3%  → автописьмо
            ("11", "iPhone 15 Pro 256 ГБ", 76000, {}),                      # 👀 +31% → карточка
            ("12", "iPhone 15 Pro 256 ГБ", 50000, {"seller_type": "company"}),  # компания
            ("13", "iPhone 15 Pro 256 ГБ на запчасти", 30000, {}),          # отсев по выдаче
            ("14", "iPhone 15 Pro 256 ГБ", 99000, {}),                      # дорого, отсев по выдаче
            ("15", "iPhone 15 Pro 256 ГБ", 55000, {"seller_reviews": 0}),   # без отзывов
            ("16", "iPhone 15 Pro 256 ГБ", 52000, {}),                      # 🔥 ниже скупки
        ]
        search[:] = []
        for item_id, title, price, extra in new:
            url = f"https://www.avito.ru/x_{item_id}"
            search.append(SearchItem(item_id, url, title, price, ""))
            cards[url] = card(item_id, title, price, url=url, **extra)
        await app.search_pass()

        assert app.queue.qsize() == 2                      # 10 и 16
        assert any("можно предложить" in t and "+31%" in t for t in app.tg.sent)
        reasons = {i: (await app.db.get_listing(i) or {}).get("filter_reason") for i in "12 13 14 15".split()}
        assert reasons["12"] == "company"
        assert reasons["13"].startswith("broken")
        assert reasons["14"] == "too_expensive"
        assert reasons["15"] == "no_reviews"

        # 3. очередь отправки в DRY RUN
        while not app.queue.empty():
            await app.process_job(app.queue.get_nowait())
            app.pending_auto -= 1
        assert await app.db.auto_sent_today() == 2
        dry = [t for t in app.tg.sent if "[DRY RUN]" in t]
        assert len(dry) == 2 and "58 000" in dry[0] + dry[1]
        assert (await app.db.get_dialog("10"))["status"] == "dry_run"

        # 4. то же объявление повторно — никогда второй раз
        await app.queue.put(sch.SendJob("10", None, "auto"))
        await app.process_job(app.queue.get_nowait())
        assert await app.db.auto_sent_today() == 2

        # 5. статистика и статус не падают
        assert "Найдено" in await app.stats_text()
        assert "Отправлено сегодня: 2/30" in await app.status_text()
        await app.db.close()

    asyncio.run(scenario())


def test_night_and_limit(tmp_path, monkeypatch):
    async def scenario():
        app = make_app(tmp_path, monkeypatch, hour=23)
        await app.db.open()
        await app.prices.refresh()
        data = card("20", "iPhone 15 Pro 256 ГБ", 60000, url="u20")
        await app.evaluate_listing(data)
        assert app.queue.qsize() == 0
        assert "ночное время" in app.tg.sent[-1]

        app2 = make_app(tmp_path, monkeypatch, hour=12)
        app2.db = app.db
        await app2.prices.refresh()
        app2.cfg.data["messaging"]["daily_message_limit"] = 0
        await app2.evaluate_listing(card("21", "iPhone 15 Pro 256 ГБ", 60000, url="u21"))
        assert any("Дневной лимит" in t for t in app2.tg.sent)
        assert "дневной лимит" in app2.tg.sent[-1]
        await app.db.close()

    asyncio.run(scenario())


def test_live_send_and_replies(tmp_path, monkeypatch):
    async def scenario():
        app = make_app(tmp_path, monkeypatch, dry_run=False)
        await app.db.open()
        await app.prices.refresh()
        sent_to = []

        async def fake_send_first(browser, url, text):
            sent_to.append((url, text))
            return "u2i-abc", "https://www.avito.ru/profile/messenger/channel/u2i-abc"

        chat = [ChatMessage("out", "приветствие", "k0")]

        async def fake_channels(browser):
            return {"u2i-abc": chat[-1].text}

        async def fake_read(browser, url, our):
            return list(chat)

        async def fake_send_in_chat(browser, url, text):
            sent_to.append((url, text))

        monkeypatch.setattr(sch, "send_first_message", fake_send_first)
        monkeypatch.setattr(sch, "list_channels", fake_channels)
        monkeypatch.setattr(sch, "read_chat", fake_read)
        monkeypatch.setattr(sch, "send_in_chat", fake_send_in_chat)

        await app.evaluate_listing(card("30", "iPhone 15 Pro 256 ГБ", 62000, url="u30"))
        await app.process_job(app.queue.get_nowait())
        assert sent_to and "58 000" in sent_to[0][1]
        d = await app.db.get_dialog("30")
        assert d["status"] == "sent" and d["chat_url"].endswith("u2i-abc")

        # другой лот того же продавца — автописьма нет
        await app.evaluate_listing(card("31", "iPhone 15 Pro 256 ГБ", 62000, url="u31", seller_id="s30"))
        assert "уже писали" in app.tg.sent[-1]

        chat.append(ChatMessage("in", "Давайте за 60, сегодня после 19 могу", "k1"))
        await app.replies_pass()
        assert "Продавец хочет: 60 000" in app.tg.sent[-1]
        assert "72 500" in app.tg.sent[-1]
        assert (await app.db.get_dialog("30"))["status"] == "counter"

        chat.append(ChatMessage("in", "Ладно, давайте, приезжайте", "k2"))
        await app.replies_pass()
        assert "СДЕЛКА" in app.tg.sent[-1]
        assert (await app.db.get_dialog("30"))["status"] == "agreed"

        # повторная проверка — те же сообщения не пересылаются
        n = len(app.tg.sent)
        chat.append(ChatMessage("out", "ок", "k3"))
        await app.replies_pass()
        assert len(app.tg.sent) == n

        # ответ из Telegram (reply на уведомление)
        listing_id = await app.db.listing_by_tg(n)
        assert listing_id == "30"
        await app.enqueue_manual("30", "Буду в 19:30")
        await app.process_job(app.queue.get_nowait())
        assert sent_to[-1] == (d["chat_url"], "Буду в 19:30")
        assert "Отправлено" in app.tg.sent[-1]
        assert "СДЕЛКА" not in await app.deals_text() and "🟢" in await app.deals_text()
        await app.db.close()

    asyncio.run(scenario())
