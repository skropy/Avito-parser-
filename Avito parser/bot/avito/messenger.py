"""Отправка сообщений продавцам и чтение ответов через веб-мессенджер Авито."""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from loguru import logger
from playwright.async_api import Error as PlaywrightError, Page

from bot.avito import selectors as S
from bot.avito.browser import AvitoBrowser, LayoutError
from bot.textutil import normalize

_OUT_RE = re.compile(r"(?:^|[\s_\-/])(?:out|outgoing|own|my|mine|right|sent|self)(?:[\s_\-/]|$)", re.I)

_MESSAGES_JS = """
(S) => {
  let els = [];
  for (const s of S.item) { try { els = [...document.querySelectorAll(s)]; } catch (e) {} if (els.length) break; }
  els = els.filter(e => !els.some(o => o !== e && e.contains(o)));
  return els.map(e => {
    let t = '';
    for (const s of S.text) { try { const x = e.querySelector(s); if (x) { t = (x.innerText || '').trim(); if (t) break; } } catch (er) {} }
    if (!t) t = (e.innerText || '').trim();
    const cls = (x) => x ? ((x.getAttribute('data-marker') || '') + ' ' + (x.className || '').toString()) : '';
    const time = e.querySelector('time');
    return {
      text: t,
      marker: cls(e) + ' ' + cls(e.parentElement),
      id: e.getAttribute('data-message-id') || e.getAttribute('data-id') || '',
      time: time ? (time.getAttribute('datetime') || time.textContent || '') : '',
    };
  });
}
"""

_CHANNELS_JS = """
(S) => {
  let els = [];
  for (const s of S.item) { try { els = [...document.querySelectorAll(s)]; } catch (e) {} if (els.length) break; }
  return els.map(e => {
    const a = e.tagName === 'A' ? e : e.querySelector('a[href*="/messenger/channel/"]');
    return { href: a ? a.getAttribute('href') : '', text: (e.innerText || '').trim().slice(0, 500) };
  }).filter(x => x.href);
}
"""


@dataclass
class ChatMessage:
    direction: str  # in / out
    text: str
    key: str


def chat_id_from_url(url: str) -> str:
    m = re.search(r"/messenger/channel/([^/?#]+)", url or "")
    return m.group(1) if m else ""


def _clean(text: str) -> str:
    text = re.sub(r"\s*(?:прочитано|доставлено|отправлено|изменено)\s*$", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*\d{1,2}:\d{2}\s*$", "", text)
    return text.strip()


def _same_text(a: str, b: str) -> bool:
    a, b = normalize(a), normalize(b)
    return bool(a and b) and (a == b or a.startswith(b) or b.startswith(a))


async def _type_and_send(browser: AvitoBrowser, page: Page, text: str) -> None:
    inp = await browser.first_visible(S.CHAT_INPUT, timeout_ms=15000, page=page)
    if not inp:
        await browser.raise_if_blocked(page)
        raise LayoutError("не нашёл поле ввода сообщения")
    await inp.click()
    await inp.fill(text)
    await page.wait_for_timeout(random.randint(600, 1400))
    btn = await browser.first_visible(S.CHAT_SEND, page=page)
    if btn:
        await btn.click()
    else:
        await inp.press("Enter")
    await page.wait_for_timeout(2500)
    try:
        left = await inp.input_value()
    except PlaywrightError:
        try:
            left = await inp.inner_text()
        except PlaywrightError:
            left = ""
    if left and normalize(text)[:20] in normalize(left):
        raise LayoutError("сообщение не ушло — текст остался в поле ввода")


async def _chat_url_on(page: Page) -> str:
    if "/messenger/channel/" in page.url:
        return page.url.split("?")[0]
    for sel in S.CHAT_LINK:
        try:
            loc = page.locator(sel)
            if await loc.count():
                href = await loc.first.get_attribute("href")
                if href:
                    return urljoin(S.BASE_URL, href).split("?")[0]
        except PlaywrightError:
            continue
    return ""


async def list_channels(browser: AvitoBrowser) -> dict[str, str]:
    """{chat_id: текст превью} для списка чатов мессенджера."""
    page = await browser.goto(S.MESSENGER_URL, settle_ms=(2500, 4000))
    raw = await page.evaluate(_CHANNELS_JS, {"item": S.CHANNEL_ITEM})
    result: dict[str, str] = {}
    for r in raw:
        cid = chat_id_from_url(r["href"])
        if cid and cid not in result:
            result[cid] = r["text"]
    return result


async def send_first_message(browser: AvitoBrowser, listing_url: str, text: str) -> tuple[str, str]:
    """Нажимает «Написать» на странице объявления и отправляет текст.
    Возвращает (chat_id, chat_url) — chat_url может быть пустым, если не нашли."""
    page = await browser.goto(listing_url)
    context = browser.context
    before = list(context.pages)
    btn = await browser.first_visible(S.WRITE_BUTTON, timeout_ms=8000)
    if not btn:
        raise LayoutError("не нашёл кнопку «Написать» на странице объявления")
    await btn.click()
    await page.wait_for_timeout(3000)
    new_pages = [p for p in context.pages if p not in before]
    target = new_pages[-1] if new_pages else page
    if new_pages:
        await target.wait_for_load_state("domcontentloaded")
    await browser.raise_if_blocked(target)

    await _type_and_send(browser, target, text)
    chat_url = await _chat_url_on(target)
    if new_pages:
        await target.close()
    if not chat_url:
        # самый свежий чат в мессенджере — тот, куда мы только что написали
        channels = await list_channels(browser)
        if channels:
            chat_url = f"{S.MESSENGER_URL}/channel/{next(iter(channels))}"
    if not chat_url:
        logger.warning("Сообщение отправлено, но ссылку на чат найти не удалось: {}", listing_url)
    return chat_id_from_url(chat_url), chat_url


async def send_in_chat(browser: AvitoBrowser, chat_url: str, text: str) -> None:
    page = await browser.goto(chat_url, settle_ms=(2000, 3500))
    await _type_and_send(browser, page, text)


async def read_chat(browser: AvitoBrowser, chat_url: str, our_texts: list[str]) -> list[ChatMessage]:
    page = await browser.goto(chat_url, settle_ms=(2500, 4000))
    raw = await page.evaluate(_MESSAGES_JS, {"item": S.MESSAGE_ITEM, "text": S.MESSAGE_TEXT})
    parsed: list[tuple[str, str, str]] = []  # (direction, text, id)
    for r in raw:
        text = _clean(r.get("text") or "")
        if not text:
            continue
        norm = normalize(text)
        if any(w in norm for w in S.SYSTEM_MESSAGE_WORDS) or "system" in (r.get("marker") or "").lower():
            continue
        is_ours = any(_same_text(text, t) for t in our_texts)
        direction = "out" if is_ours or _OUT_RE.search(r.get("marker") or "") else "in"
        parsed.append((direction, text, r.get("id") or ""))

    # входящие до нашего первого сообщения — карточка объявления и служебное;
    # если своё сообщение распознать не удалось, берём всё, чтобы не потерять ответы
    started = not any(d == "out" for d, _, _ in parsed)
    messages: list[ChatMessage] = []
    seen_counts: dict[str, int] = {}
    for direction, text, msg_id in parsed:
        if direction == "out":
            started = True
        if not started:
            continue
        norm = normalize(text)
        n = seen_counts.get(norm, 0)
        seen_counts[norm] = n + 1
        key = msg_id or hashlib.sha1(f"{norm}|{n}".encode()).hexdigest()[:16]
        messages.append(ChatMessage(direction=direction, text=text, key=key))
    return messages
