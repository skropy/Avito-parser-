"""Парсинг выдачи поиска (только первая страница)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bot.avito import selectors as S
from bot.avito.browser import AvitoBrowser
from bot.textutil import parse_price

_SEARCH_JS = """
(S) => {
  const q = (sels, root) => { for (const s of sels) { try { const e = root.querySelector(s); if (e) return e; } catch (e) {} } return null; };
  const txt = (sels, root) => { const e = q(sels, root); return e ? (e.innerText || e.textContent || '').trim() : ''; };
  const root = q(S.container, document) || document;
  return [...root.querySelectorAll(S.item)].map(el => {
    const a = q(S.link, el);
    const meta = el.querySelector(S.priceMeta);
    return {
      id: el.getAttribute('data-item-id') || (el.id || '').replace(/^i/, ''),
      url: a ? a.getAttribute('href') : '',
      title: txt(S.title, el) || (a ? (a.getAttribute('title') || a.innerText || '') : ''),
      price_raw: meta ? meta.getAttribute('content') : txt(S.price, el),
      date: txt(S.date, el),
    };
  });
}
"""


@dataclass
class SearchItem:
    id: str
    url: str
    title: str
    price: int | None
    date: str


def item_id_from_url(url: str) -> str:
    m = re.search(r"_(\d{6,})(?:[/?#]|$)", url or "")
    return m.group(1) if m else ""


async def fetch_search(browser: AvitoBrowser, url: str) -> list[SearchItem]:
    page = await browser.goto(url)
    raw = await page.evaluate(_SEARCH_JS, {
        "container": S.SEARCH_CONTAINER, "item": S.SEARCH_ITEM, "link": S.SEARCH_ITEM_LINK,
        "title": S.SEARCH_ITEM_TITLE, "priceMeta": S.SEARCH_ITEM_PRICE_META,
        "price": S.SEARCH_ITEM_PRICE, "date": S.SEARCH_ITEM_DATE,
    })
    items: list[SearchItem] = []
    seen: set[str] = set()
    for r in raw:
        full_url = urljoin(S.BASE_URL, r.get("url") or "").split("?")[0]
        item_id = str(r.get("id") or "").strip() or item_id_from_url(full_url)
        if not item_id or not full_url or item_id in seen:
            continue
        seen.add(item_id)
        items.append(SearchItem(
            id=item_id, url=full_url, title=" ".join((r.get("title") or "").split()),
            price=parse_price(r.get("price_raw")), date=r.get("date") or "",
        ))
    return items
