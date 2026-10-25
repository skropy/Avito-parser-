"""Парсинг карточки объявления и данных продавца."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from bot.avito import selectors as S
from bot.avito.browser import AvitoBrowser
from bot.avito.search import item_id_from_url
from bot.textutil import normalize, parse_price

_LISTING_JS = """
(S) => {
  const q = (sels, root) => { for (const s of sels) { try { const e = (root || document).querySelector(s); if (e) return e; } catch (e) {} } return null; };
  const txt = (sels, root) => { const e = q(sels, root); return e ? (e.innerText || e.textContent || '').trim() : ''; };
  const priceEl = q(S.price);
  let photos = [];
  for (const s of S.photos) {
    try {
      photos = [...document.querySelectorAll(s)]
        .map(i => i.getAttribute('src') || i.getAttribute('data-src') || '')
        .filter(u => u && u.startsWith('http'));
    } catch (e) {}
    if (photos.length) break;
  }
  const og = document.querySelector("meta[property='og:image']");
  if (!photos.length && og) photos = [og.getAttribute('content')];
  const seller = q(S.sellerBlock);
  const link = q(S.sellerLink, seller) || q(S.sellerLink);
  const metro = [];
  for (const s of S.metro) {
    try { document.querySelectorAll(s).forEach(e => { const t = (e.innerText || '').trim(); if (t && t.length < 40) metro.push(t); }); } catch (e) {}
    if (metro.length) break;
  }
  return {
    title: txt(S.title),
    price_raw: priceEl ? (priceEl.getAttribute('content') || priceEl.innerText || '') : '',
    description: txt(S.description),
    photos: [...new Set(photos)].slice(0, 3),
    address: txt(S.address),
    metro: metro.slice(0, 2),
    item_id: txt(S.itemId),
    date: txt(S.date),
    seller_block: seller ? (seller.innerText || '').slice(0, 1500) : '',
    seller_name: txt(S.sellerName, seller) || txt(S.sellerName),
    seller_label: txt(S.sellerLabel, seller) || txt(S.sellerLabel),
    seller_href: link ? link.getAttribute('href') : '',
    seller_rating: txt(S.sellerRating, seller) || txt(S.sellerRating),
    seller_reviews: txt(S.sellerReviews, seller) || txt(S.sellerReviews),
  };
}
"""


def _seller_id(href: str) -> str | None:
    m = re.search(r"/(?:user|brands)/([^/?#]+)", href or "")
    return m.group(1) if m else None


def _reviews(*texts: str) -> int | None:
    for t in texts:
        n = normalize(t)
        if not n:
            continue
        if "нет отзыв" in n or "отзывов пока нет" in n:
            return 0
        m = re.search(r"(\d+)\s*отзыв", n)
        if m:
            return int(m.group(1))
    return None


def _rating(*texts: str) -> float | None:
    for t in texts:
        m = re.search(r"(?<!\d)([1-5][.,]\d)(?!\d)", t or "")
        if m:
            return float(m.group(1).replace(",", "."))
    return None


def _active_listings(text: str) -> int | None:
    m = re.search(r"(\d+)\s+(?:активн[а-я]*\s+)?объявлен", normalize(text))
    return int(m.group(1)) if m else None


def _seller_type(label: str, href: str, block: str) -> str:
    text = normalize(f"{label} {block[:300]}")
    if "/brands/" in (href or "") or any(w in text for w in ("компания", "магазин", "агентство", "реквизиты проверены")):
        return "company"
    if "частное лицо" in text or label:
        return "private"
    return "unknown"


def battery_from_text(text: str) -> int | None:
    m = re.search(
        r"(?:акб|аккумулятор[а-я]*|батаре[а-я]*|емкост[а-я]*|ёмкост[а-я]*|battery|здоровье)[^\d]{0,15}(\d{2,3})\s*%",
        normalize(text),
    )
    if m and 50 <= int(m.group(1)) <= 100:
        return int(m.group(1))
    m = re.search(r"(\d{2,3})\s*%\s*(?:акб|аккумулятор|батаре|емкост)", normalize(text))
    if m and 50 <= int(m.group(1)) <= 100:
        return int(m.group(1))
    return None


async def fetch_listing(browser: AvitoBrowser, url: str) -> dict:
    page = await browser.goto(url, settle_ms=(2000, 4000))
    raw = await page.evaluate(_LISTING_JS, {
        "title": S.ITEM_TITLE, "price": S.ITEM_PRICE, "description": S.ITEM_DESCRIPTION,
        "photos": S.ITEM_PHOTOS, "address": S.ITEM_ADDRESS, "metro": S.ITEM_METRO,
        "itemId": S.ITEM_ID, "date": S.ITEM_DATE, "sellerBlock": S.SELLER_BLOCK,
        "sellerName": S.SELLER_NAME, "sellerLabel": S.SELLER_LABEL, "sellerLink": S.SELLER_LINK,
        "sellerRating": S.SELLER_RATING, "sellerReviews": S.SELLER_REVIEWS,
    })
    item_id = re.sub(r"\D", "", raw.get("item_id") or "") or item_id_from_url(url)
    block = raw.get("seller_block") or ""
    href = raw.get("seller_href") or ""
    description = raw.get("description") or ""
    name = (raw.get("seller_name") or "").split("\n")[0].strip()
    return {
        "id": item_id,
        "url": url,
        "title": " ".join((raw.get("title") or "").split()),
        "price": parse_price(raw.get("price_raw")),
        "description": description,
        "photos": raw.get("photos") or [],
        "address": " ".join((raw.get("address") or "").split())[:150],
        "metro": raw.get("metro") or [],
        "published": raw.get("date") or "",
        "seller_name": name,
        "seller_id": _seller_id(href),
        "seller_url": urljoin(S.BASE_URL, href) if href else "",
        "seller_type": _seller_type(raw.get("seller_label") or "", href, block),
        "seller_rating": _rating(raw.get("seller_rating") or "", block),
        "seller_reviews": _reviews(raw.get("seller_reviews") or "", block),
        "seller_active_listings": _active_listings(block),
        "battery": battery_from_text(description),
    }
