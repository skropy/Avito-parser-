"""Главная логика: циклы поиска, отправки, чтения ответов, лимиты, рабочее время, пауза."""
from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from loguru import logger
from playwright.async_api import Error as PlaywrightError

from bot import filters
from bot.avito import selectors as S
from bot.avito.browser import AvitoBlocked, AvitoBrowser, BLOCK_LOGIN, LayoutError, NetworkError
from bot.avito.listing import fetch_listing
from bot.avito.messenger import list_channels, read_chat, send_first_message, send_in_chat
from bot.avito.search import SearchItem, fetch_search
from bot.config import DATA_DIR, Config
from bot.pricing.decision import WATCH, decide
from bot.pricing.model_parser import memory_label, parse_listing
from bot.pricing.sheet import PriceTable
from bot.replies import classify, find_amount
from bot.storage import Storage
from bot.telegram import keyboards, templates
from bot.telegram.bot import TelegramUI
from bot.textutil import fmt_rub


@dataclass
class SendJob:
    listing_id: str
    text: str | None   # None — взять случайный шаблон
    kind: str          # auto — автописьмо, manual — по кнопке/ответу из Telegram
    created: float = field(default_factory=time.time)


class App:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.tz = ZoneInfo(cfg.timezone)
        self.db = Storage(DATA_DIR / "bot.db", cfg.timezone)
        self.browser = AvitoBrowser(cfg)
        self.prices = PriceTable(cfg)
        self.tg = TelegramUI(cfg, self)
        self.queue: asyncio.Queue[SendJob] = asyncio.Queue()

        self.pending_auto = 0           # автописьма в очереди (для лимита)
        self.manual_pause = False
        self.autowrite = True
        self.block_kind: str | None = None
        self.block_since = 0.0
        self.block_reminded = 0.0
        self.last_check: datetime | None = None
        self.last_check_new = 0
        self.failed_passes = 0
        self.failed_notified = False
        self.empty_passes = 0
        self.price_error_notified = False
        self.next_send_at = 0.0
        self._rr = 0

    # ================================================================ запуск
    async def run(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        await self.db.open()
        self.autowrite = (await self.db.kv_get("autowrite", "1")) == "1"
        await self.refresh_prices()
        await self.browser.start()

        mode = "🧪 режим DRY RUN — продавцам ничего не отправляется" if self.cfg.dry_run else "⚡️ боевой режим"
        await self.tg.send(f"🤖 Бот запущен, {mode}.\nКоманды — /help")
        await self._check_login()

        tasks = [
            asyncio.create_task(self.tg.run(), name="telegram"),
            asyncio.create_task(self._search_loop(), name="search"),
            asyncio.create_task(self._sender_loop(), name="sender"),
            asyncio.create_task(self._replies_loop(), name="replies"),
            asyncio.create_task(self._block_watch_loop(), name="block_watch"),
            asyncio.create_task(self._prices_loop(), name="prices"),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for t in done:
                if t.exception():
                    raise t.exception()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        for coro in (self.tg.stop(), self.browser.stop(), self.db.close()):
            try:
                await coro
            except Exception:
                pass

    async def _check_login(self) -> None:
        try:
            async with self.browser.lock:
                await self.browser.goto(S.BASE_URL)
                logged = await self.browser.is_logged_in()
            if not logged:
                await self.tg.send("🔑 Похоже, вы не вошли в аккаунт Авито. Войдите в рабочий аккаунт в окне "
                                   "браузера на Mac — без этого бот не сможет писать продавцам.")
        except AvitoBlocked as e:
            await self.on_blocked(e.kind)
        except Exception as e:
            logger.warning("Не удалось проверить вход в Авито: {}", e)

    # ============================================================ состояние
    @property
    def paused(self) -> bool:
        return self.manual_pause or self.block_kind is not None

    async def wait_active(self) -> None:
        while self.paused:
            await asyncio.sleep(2)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def in_work_hours(self) -> bool:
        h = self.now().hour
        return int(self.cfg.get("messaging.work_hours_start", 9)) <= h < int(self.cfg.get("messaging.work_hours_end", 22))

    def set_manual_pause(self, value: bool) -> None:
        self.manual_pause = value
        logger.info("Ручная пауза: {}", value)

    async def set_autowrite(self, value: bool) -> None:
        self.autowrite = value
        await self.db.kv_set("autowrite", "1" if value else "0")

    # ============================================================ таблица цен
    async def _prices_loop(self) -> None:
        while True:
            await asyncio.sleep(20)
            if self.prices.due():
                await self.refresh_prices()

    async def refresh_prices(self) -> bool:
        try:
            await self.prices.refresh()
            if self.price_error_notified:
                await self.tg.send("✅ Таблица цен снова читается.")
            self.price_error_notified = False
            return True
        except Exception as e:
            logger.error("Не удалось прочитать таблицу цен: {}", e)
            if not self.price_error_notified:
                tail = ("Работаю по последней загруженной версии." if self.prices.is_loaded
                        else "Пока таблица не загрузится, объявления не оцениваются.")
                await self.tg.send(f"⚠️ Не удалось прочитать таблицу цен: {escape(str(e))}\n{tail}")
                self.price_error_notified = True
            return False

    # ================================================================= поиск
    async def _search_loop(self) -> None:
        while True:
            await self.wait_active()
            try:
                await self.search_pass()
                await self._pass_ok()
            except AvitoBlocked as e:
                await self.on_blocked(e.kind)
            except (NetworkError, PlaywrightError, LayoutError) as e:
                await self._pass_failed(e)
            except Exception as e:
                logger.exception("Ошибка в проходе поиска")
                await self._pass_failed(e)
            interval = float(self.cfg.get("search.check_interval_sec", 60))
            jitter = float(self.cfg.get("search.check_jitter_sec", 15))
            await asyncio.sleep(interval + random.uniform(0, jitter))

    async def _pass_ok(self) -> None:
        if self.failed_notified:
            await self.tg.send("✅ Связь с Авито восстановилась.")
        self.failed_passes = 0
        self.failed_notified = False

    async def _pass_failed(self, e: Exception) -> None:
        self.failed_passes += 1
        logger.warning("Проход не удался ({} подряд): {}", self.failed_passes, str(e)[:300])
        limit = int(self.cfg.get("protection.notify_after_failed_passes", 5))
        if self.failed_passes >= limit and not self.failed_notified:
            self.failed_notified = True
            await self.tg.send(f"⚠️ {self.failed_passes} проходов подряд не удались. Последняя ошибка:\n"
                               f"<code>{escape(str(e)[:500])}</code>\nПроверьте интернет и окно браузера.")

    async def search_pass(self) -> None:
        url = str(self.cfg.get("search.search_url"))
        async with self.browser.lock:
            items = await fetch_search(self.browser, url)
            if not items:
                self.empty_passes += 1
                shot = None
                if self.empty_passes == int(self.cfg.get("protection.empty_page_alert_passes", 3)):
                    shot = await self.browser.screenshot("layout_changed.png")
        self.last_check = self.now()
        if not items:
            logger.warning("В выдаче 0 объявлений ({} раз подряд)", self.empty_passes)
            if shot:
                await self.tg.send_file_photo(
                    shot, "🧩 Похоже, Авито изменил вёрстку: на странице поиска не найдено ни одного "
                          "объявления 3 раза подряд. Нужно обновить селекторы в bot/avito/selectors.py")
            return
        self.empty_passes = 0

        if not await self.db.kv_get("initialized"):
            await self.db.mark_seen([{"id": i.id, "url": i.url, "title": i.title, "price": i.price} for i in items])
            await self.db.kv_set("initialized", "1")
            logger.info("Первый запуск: {} объявлений помечены как просмотренные", len(items))
            await self.tg.send(f"👋 Первый запуск: {len(items)} текущих объявлений помечены как просмотренные. "
                               f"Дальше буду присылать только новые.")
            return

        if not self.prices.is_loaded:
            logger.warning("Таблица цен не загружена — новые объявления пока не оцениваю")
            return

        stop = int(self.cfg.get("search.known_streak_stop", 5))
        new: list[SearchItem] = []
        streak = 0
        for it in items:
            if await self.db.is_known(it.id):
                streak += 1
                if streak >= stop:
                    break
                continue
            streak = 0
            new.append(it)
        self.last_check_new = len(new)
        if new:
            logger.info("Новых объявлений: {}", len(new))
        for it in new[: int(self.cfg.get("search.max_new_per_pass", 15))]:
            await self.wait_active()
            await self.process_item(it)

    # ===================================================== разбор объявления
    def _prefilter(self, it: SearchItem) -> dict | None:
        """Отсев по данным выдачи, чтобы не открывать лишние карточки."""
        if it.price and it.price < int(self.cfg.get("filters.min_sane_price", 5000)):
            return {"filter_reason": "low_price"}
        broken = filters.check_stop_words(it.title, "", self.cfg)
        if broken:
            return {"filter_reason": broken}
        pr = parse_listing(it.title, "", self.prices.matcher)
        if pr.model_key and pr.memory and it.price:
            row = self.prices.get(pr.model_key, pr.memory)
            if not row:
                return {"filter_reason": "not_in_table", "model_name": self.prices.models.get(pr.model_key),
                        "memory": pr.memory}
            if it.price > row.buy * (1 + float(self.cfg.get("pricing.notify_max_pct", 40)) / 100):
                return {"filter_reason": "too_expensive", "model_name": row.model, "memory": pr.memory}
        return None

    async def process_item(self, it: SearchItem) -> None:
        pre = self._prefilter(it)
        if pre:
            await self.db.save_listing({"id": it.id, "url": it.url, "title": it.title, "price": it.price, **pre})
            logger.debug("Отсеяно по выдаче: {} — {} ({})", it.id, it.title, pre["filter_reason"])
            return
        try:
            async with self.browser.lock:
                data = await fetch_listing(self.browser, it.url)
        except (AvitoBlocked, NetworkError):
            raise
        except Exception as e:
            logger.exception("Не удалось разобрать карточку {}", it.url)
            await self.db.save_listing({"id": it.id, "url": it.url, "title": it.title, "price": it.price,
                                        "filter_reason": f"parse_error:{type(e).__name__}"})
            return
        data["id"] = it.id
        data["url"] = it.url
        data["title"] = data.get("title") or it.title
        data["price"] = data.get("price") or it.price
        await self.evaluate_listing(data)

    async def evaluate_listing(self, data: dict) -> None:
        cfg = self.cfg
        reason = filters.check_listing(data, cfg)
        pr = parse_listing(data["title"], data.get("description", ""), self.prices.matcher)
        if pr.model_key:
            data["model_key"] = pr.model_key
            data["model_name"] = self.prices.models.get(pr.model_key, pr.model_key)
        if pr.memory:
            data["memory"] = pr.memory
            data["memory_label"] = memory_label(pr.memory)
        if not reason and pr.reason:
            reason = pr.reason
            logger.info("Не определил модель/память: «{}» ({})", data["title"], pr.reason)

        row = None
        if not reason:
            row = self.prices.get(pr.model_key, pr.memory)
            if not row:
                reason = "not_in_table"
        data["zone"] = None
        if row and not reason:
            d = decide(
                data["price"], row,
                auto_pct=float(cfg.get("pricing.auto_write_max_pct", 25)),
                notify_pct=float(cfg.get("pricing.notify_max_pct", 40)),
                hot_discount=int(cfg.get("pricing.hot_discount", 0)),
                round_to=int(cfg.get("pricing.offer_round_to", 500)),
            )
            data.update(model_name=row.model, buy=row.buy, sell=row.sell, offer=d.offer, pct=d.pct,
                        profit=d.profit, max_price=d.max_price, zone=d.zone)
            if d.zone is None:
                reason = "too_expensive"
        data["filter_reason"] = reason
        await self.db.save_listing(data)
        logger.info("{} | {} | {} | {}", data["id"], data["title"][:60], fmt_rub(data.get("price")),
                    filters.reason_title(reason) if reason else f"ЗОНА {data['zone']}")
        if not reason:
            await self.act_on_listing(data)

    async def act_on_listing(self, data: dict) -> None:
        if data["zone"] == WATCH:
            await self.send_watch(data, "zone")
            return
        why = await self.autowrite_block_reason(data, count_pending=True)
        if why:
            await self.send_watch(data, why)
            return
        self.pending_auto += 1
        await self.queue.put(SendJob(data["id"], None, "auto"))

    async def autowrite_block_reason(self, data: dict, count_pending: bool) -> str | None:
        if not self.autowrite:
            return "autowrite_off"
        if not self.in_work_hours():
            return "night"
        if await self.db.get_dialog(data["id"]) or await self.db.seller_contacted(data.get("seller_id")):
            return "seller_contacted"
        limit = int(self.cfg.get("messaging.daily_message_limit", 30))
        used = await self.db.auto_sent_today() + (self.pending_auto if count_pending else 0)
        if used >= limit:
            if not await self.db.limit_notified_today():
                await self.db.set_limit_notified()
                await self.tg.send(f"📵 Дневной лимит {limit} автосообщений исчерпан. До полуночи присылаю "
                                   f"только карточки с кнопкой «Написать продавцу».")
            return "limit"
        return None

    async def send_watch(self, data: dict, reason: str) -> None:
        ids = await self.tg.send_card(templates.watch_card(data, reason),
                                      keyboards.watch(data["id"], data["url"]), data.get("photos"))
        await self.db.link_tg(ids, data["id"])

    # ============================================================== отправка
    def render_template(self, listing: dict) -> str:
        templates_list = self.cfg.words("messaging.templates") or ["Здравствуйте! Предлагаю {offer} ₽ за {model}."]
        text = random.choice(templates_list)
        offer = f"{int(listing.get('offer') or 0):,}".replace(",", " ")
        text = (text.replace("{model}", listing.get("model_name") or "телефон")
                    .replace("{memory}", listing.get("memory_label") or "")
                    .replace("{offer}", offer))
        return " ".join(text.split())

    async def enqueue_manual(self, listing_id: str, text: str | None) -> str:
        listing = await self.db.get_listing(listing_id)
        if not listing:
            return "Объявление не найдено в базе."
        await self.queue.put(SendJob(listing_id, text, "manual"))
        waiting = max(0, int(self.next_send_at - time.time()))
        note = f" (пауза между отправками — ещё ~{waiting} с)" if waiting > 5 else ""
        if self.paused:
            note += "\n⏸ Бот сейчас на паузе — отправлю после продолжения."
        return f"⏳ Поставил в очередь на отправку{note}"

    def _schedule_next_send(self) -> None:
        pause = random.uniform(float(self.cfg.get("messaging.send_pause_min_sec", 30)),
                               float(self.cfg.get("messaging.send_pause_max_sec", 120)))
        self.next_send_at = time.time() + pause

    async def _sender_loop(self) -> None:
        while True:
            job = await self.queue.get()
            requeued = False
            try:
                await self.wait_active()
                delay = self.next_send_at - time.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                await self.wait_active()
                await self.process_job(job)
            except AvitoBlocked as e:
                await self.on_blocked(e.kind)
                await self.queue.put(job)
                requeued = True
            except Exception as e:
                logger.exception("Не удалось отправить сообщение по {}", job.listing_id)
                listing = await self.db.get_listing(job.listing_id)
                if job.kind == "auto" and listing:
                    await self.send_watch(listing, "send_failed")
                else:
                    await self.tg.send(f"❌ Не удалось отправить сообщение: {escape(str(e)[:300])}")
            finally:
                if job.kind == "auto" and not requeued:
                    self.pending_auto = max(0, self.pending_auto - 1)

    async def process_job(self, job: SendJob) -> None:
        listing = await self.db.get_listing(job.listing_id)
        if not listing:
            return
        dialog = await self.db.get_dialog(job.listing_id)

        if job.kind == "auto":
            if dialog:
                logger.info("Объявлению {} уже писали — пропускаю", job.listing_id)
                return
            why = await self.autowrite_block_reason(listing, count_pending=False)
            if why:  # пока ждали очереди, наступила ночь или кончился лимит
                await self.send_watch(listing, why)
                return
            await self._send_first(listing, self.render_template(listing), auto=True)
            return

        # ручная отправка из Telegram
        if not dialog:
            await self._send_first(listing, job.text or self.render_template(listing), auto=False)
        elif job.text is None:
            await self.tg.send("Этому продавцу уже писали — первое сообщение повторно не отправляю.")
        elif dialog["status"] == "dry_run" or self.cfg.dry_run:
            await self.db.add_message(dialog["id"], "out", job.text)
            await self.tg.send(f"[DRY RUN] ✉️ Отправил бы продавцу: «{escape(job.text)}»")
            self._schedule_next_send()
        elif not dialog.get("chat_url"):
            await self.tg.send("Не знаю ссылку на чат с этим продавцом — ответьте вручную на Авито.",
                               keyboards.dialog(listing["id"], None, listing["url"]))
        else:
            async with self.browser.lock:
                await send_in_chat(self.browser, dialog["chat_url"], job.text)
            await self.db.add_message(dialog["id"], "out", job.text)
            self._schedule_next_send()
            ids = await self.tg.send(f"✉️ Отправлено: «{escape(job.text)}»",
                                     keyboards.dialog(listing["id"], dialog["chat_url"], listing["url"]))
            await self.db.link_tg(ids, listing["id"])

    async def _send_first(self, listing: dict, text: str, auto: bool) -> None:
        dry = self.cfg.dry_run
        chat_id = chat_url = None
        if dry:
            logger.info("[DRY RUN] отправил бы {}: {}", listing["url"], text)
            status = "dry_run"
        else:
            async with self.browser.lock:
                chat_id, chat_url = await send_first_message(self.browser, listing["url"], text)
            logger.info("Написал продавцу {}: {}", listing["url"], text)
            status = "sent"
        dialog_id = await self.db.create_dialog(
            listing["id"], chat_id or None, chat_url or None, listing.get("offer"), listing.get("max_price"),
            status, auto, None if dry else listing.get("seller_id"),
        )
        await self.db.add_message(dialog_id, "out", text)
        if auto:
            await self.db.inc_auto_sent()
        self._schedule_next_send()

        card = templates.written_card(listing, text, dry, manual=not auto)
        if auto:
            ids = await self.tg.send_card(card, keyboards.written(listing["id"], listing["url"]), listing.get("photos"))
        else:
            ids = await self.tg.send("✉️ Отправлено\n\n" + card,
                                     keyboards.dialog(listing["id"], chat_url, listing["url"]))
        await self.db.link_tg(ids, listing["id"])

    # =============================================================== ответы
    async def _replies_loop(self) -> None:
        while True:
            await asyncio.sleep(float(self.cfg.get("messaging.reply_check_interval_sec", 90)))
            await self.wait_active()
            try:
                await self.replies_pass()
            except AvitoBlocked as e:
                await self.on_blocked(e.kind)
            except Exception:
                logger.exception("Ошибка при проверке ответов")

    async def replies_pass(self) -> None:
        dialogs = await self.db.active_dialogs(int(self.cfg.get("messaging.dialog_active_days", 7)))
        if not dialogs:
            return
        async with self.browser.lock:
            channels = await list_channels(self.browser)
        to_read: list[tuple[dict, str | None]] = []
        if channels:
            for d in dialogs:
                preview = channels.get(d.get("avito_chat_id") or "")
                if preview is not None and preview != (d.get("last_preview") or ""):
                    to_read.append((d, preview))
        else:
            # список чатов не распознался — читаем диалоги по кругу, по 5 за раз
            start = self._rr % len(dialogs)
            to_read = [(d, None) for d in (dialogs + dialogs)[start:start + min(5, len(dialogs))]]
            self._rr += 5

        for d, preview in to_read:
            await self.wait_active()
            our = await self.db.outgoing_texts(d["id"])
            async with self.browser.lock:
                msgs = await read_chat(self.browser, d["chat_url"], our)
            known = await self.db.message_keys(d["id"])
            for m in msgs:
                if m.direction != "in" or m.key in known:
                    continue
                known.add(m.key)
                await self.handle_incoming(d, m.text, m.key)
            if preview is not None:
                await self.db.update_dialog(d["id"], last_preview=preview)

    async def handle_incoming(self, d: dict, text: str, key: str) -> None:
        listing = await self.db.get_listing(d["listing_id"]) or {"id": d["listing_id"], "url": d.get("chat_url") or ""}
        await self.db.add_message(d["id"], "in", text, key)
        c = classify(text, self.cfg.words("replies.agree_words"), self.cfg.words("replies.refuse_words"),
                     offer=d.get("offer"), min_amount=int(self.cfg.get("replies.counter_min_amount", 1000)))
        status = {"agreed": "agreed", "refused": "refused", "counter": "counter"}.get(c.kind)
        if status is None:
            status = d["status"] if d["status"] in ("agreed", "counter") else "replied"
        d["status"] = status
        await self.db.update_dialog(d["id"], status=status)
        logger.info("Ответ продавца по {}: «{}» → {}", d["listing_id"], text[:100], c.kind)

        kb = keyboards.dialog(listing["id"], d.get("chat_url"), listing.get("url") or d.get("chat_url"))
        if c.kind == "agreed":
            body = templates.deal_card(listing, d, text)
        else:
            body = templates.reply_card(listing, d, text, c.kind, c.amount)
        ids = await self.tg.send(body, kb)
        await self.db.link_tg(ids, listing["id"])

    # ===================================================== капча / вход
    async def on_blocked(self, kind: str) -> None:
        if self.block_kind:
            return
        self.block_kind = kind
        self.block_since = self.block_reminded = time.time()
        logger.warning("Авито: {} — все циклы на паузе", kind)
        await self.tg.send(self._block_text(), keyboards.resume())

    def _block_text(self) -> str:
        if self.block_kind == BLOCK_LOGIN:
            return "⚠️ Авито просит вход — войди в аккаунт в окне браузера на Mac, затем нажми «Продолжить»."
        return "⚠️ Авито просит капчу — пройди в окне браузера на Mac, затем нажми «Продолжить»."

    async def _block_cleared(self) -> bool:
        async with self.browser.lock:
            kind = await self.browser.detect_block()
        if kind:
            return False
        minutes = int((time.time() - self.block_since) / 60)
        self.block_kind = None
        logger.info("Капча/вход пройдены, продолжаю (пауза {} мин)", minutes)
        await self.tg.send("▶️ Работаю дальше")
        return True

    async def request_resume(self) -> str:
        if not self.block_kind:
            if self.manual_pause:
                return "Бот на ручной паузе — отправьте /resume"
            return "▶️ Бот и так работает."
        if await self._block_cleared():
            return ""
        return "Всё ещё вижу капчу/вход в окне браузера. Пройдите и нажмите «Продолжить» ещё раз."

    async def _block_watch_loop(self) -> None:
        while True:
            await asyncio.sleep(float(self.cfg.get("protection.captcha_recheck_sec", 30)))
            if not self.block_kind:
                continue
            try:
                if await self._block_cleared():
                    continue
            except Exception:
                logger.exception("Ошибка при проверке капчи")
            remind = float(self.cfg.get("protection.captcha_remind_min", 30)) * 60
            if time.time() - self.block_reminded >= remind:
                self.block_reminded = time.time()
                minutes = int((time.time() - self.block_since) / 60)
                await self.tg.send(f"⏰ Напоминание: бот стоит на паузе уже {minutes} мин.\n" + self._block_text(),
                                   keyboards.resume())

    # ============================================================== команды
    async def status_text(self) -> str:
        if self.block_kind:
            since = datetime.fromtimestamp(self.block_since, self.tz).strftime("%H:%M")
            state = f"⚠️ Пауза: Авито просит {'вход' if self.block_kind == BLOCK_LOGIN else 'капчу'} (с {since})"
        elif self.manual_pause:
            state = "⏸ Пауза (вручную, /resume)"
        else:
            state = "▶️ Работает"
        limit = int(self.cfg.get("messaging.daily_message_limit", 30))
        sent = await self.db.auto_sent_today()
        last = self.last_check.strftime("%H:%M:%S") if self.last_check else "ещё не было"
        hours = f"{self.cfg.get('messaging.work_hours_start', 9)}:00–{self.cfg.get('messaging.work_hours_end', 22)}:00"
        prices = (f"{self.prices.source}, {len(self.prices.rows)} строк, обновлена "
                  f"{datetime.fromtimestamp(self.prices.loaded_at, self.tz).strftime('%H:%M')}"
                  if self.prices.is_loaded else "не загружена")
        lines = [
            f"<b>{state}</b>",
            f"Режим: {'🧪 DRY RUN (продавцам не пишу)' if self.cfg.dry_run else '⚡️ боевой'}",
            f"Автописьма: {'включены' if self.autowrite else 'выключены'} · рабочее время {hours} "
            f"({'сейчас да' if self.in_work_hours() else 'сейчас нет'})",
            f"Последняя проверка: {last} (новых: {self.last_check_new})",
            f"Отправлено сегодня: {sent}/{limit} · в очереди: {self.queue.qsize()}",
            f"Таблица цен: {prices}",
        ]
        if self.prices.last_error:
            lines.append(f"⚠️ Ошибка таблицы: {escape(self.prices.last_error[:200])}")
        if self.failed_passes:
            lines.append(f"⚠️ Неудачных проходов подряд: {self.failed_passes}")
        return "\n".join(lines)

    async def stats_text(self) -> str:
        today = await self.db.stats(1)
        week = await self.db.stats(7)
        return templates.stats_text("📊 Сегодня", today) + "\n\n" + templates.stats_text("📊 За 7 дней", week)

    async def deals_text(self) -> str:
        rows = await self.db.deals()
        if not rows:
            return "Пока нет диалогов со статусом «согласен» или «торг»."
        lines = ["<b>Сделки и торг</b>"]
        for r in rows:
            l = json.loads(r["listing_data"]) if r.get("listing_data") else {}
            name = escape(f"{l.get('model_name', '')} {l.get('memory_label', '')}".strip() or r["listing_id"])
            link = r.get("chat_url") or l.get("url", "")
            if r["status"] == "agreed":
                lines.append(f"🟢 {name} — за {fmt_rub(r['offer'])} · <a href=\"{escape(link)}\">чат</a>")
            else:
                amount = find_amount(r.get("last_in") or "")
                lines.append(f"💸 {name} — хочет {fmt_rub(amount)} (макс. {fmt_rub(r['max_price'])}) · "
                             f"<a href=\"{escape(link)}\">чат</a>")
        return "\n".join(lines)

    async def reload(self) -> str:
        try:
            self.cfg.reload()
        except Exception as e:
            return f"❌ Ошибка в config.yaml: {escape(str(e)[:500])}\nСтарые настройки продолжают действовать."
        ok = await self.refresh_prices()
        mode = "DRY RUN" if self.cfg.dry_run else "боевой"
        if ok:
            return f"✅ Перечитал config.yaml (режим: {mode}) и таблицу цен: {len(self.prices.rows)} строк."
        return f"✅ config.yaml перечитан (режим: {mode}), но таблица цен не прочиталась — см. сообщение выше."
