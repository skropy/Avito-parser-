"""Фильтры объявлений. Каждая функция возвращает причину отсева или None."""
from __future__ import annotations

from bot.config import Config
from bot.textutil import find_phrases, normalize, remove_phrases

REASON_TITLES = {
    "no_price": "нет цены",
    "low_price": "подозрительно низкая цена",
    "broken": "запчасти / неисправен",
    "company": "компания",
    "shop_words": "слова магазина",
    "too_many_listings": "много объявлений у продавца",
    "no_reviews": "нет отзывов",
    "seller_info_missing": "не удалось прочитать продавца",
    "model_unknown": "модель не определена",
    "model_ambiguous": "несколько моделей",
    "memory_unknown": "память не определена",
    "memory_ambiguous": "несколько вариантов памяти",
    "not_in_table": "нет в таблице цен",
    "too_expensive": "дороже +40%",
    "seller_already_contacted": "продавцу уже писали",
    "parse_error": "ошибка разбора карточки",
}


def check_price(price: int | None, cfg: Config) -> str | None:
    if not price:
        return "no_price"
    if price < int(cfg.get("filters.min_sane_price", 5000)):
        return "low_price"
    return None


def check_stop_words(title: str, description: str, cfg: Config) -> str | None:
    text = normalize(f"{title} \n {description}")
    text = remove_phrases(text, cfg.words("filters.stop_word_exceptions"))
    found = find_phrases(text, cfg.words("filters.stop_words"))
    return f"broken:{found[0]}" if found else None


def check_seller(listing: dict, cfg: Config) -> str | None:
    if listing.get("seller_type") == "company":
        return "company"
    text = normalize(f"{listing.get('title', '')} \n {listing.get('description', '')}")
    found = find_phrases(text, cfg.words("filters.shop_words"))
    if found:
        return f"shop_words:{found[0]}"
    active = listing.get("seller_active_listings")
    if active is not None and active > int(cfg.get("filters.max_seller_active_listings", 5)):
        return "too_many_listings"
    reviews = listing.get("seller_reviews")
    if reviews is None:
        return "seller_info_missing"
    if reviews < int(cfg.get("filters.min_seller_reviews", 1)):
        return "no_reviews"
    return None


def check_listing(listing: dict, cfg: Config) -> str | None:
    return (
        check_price(listing.get("price"), cfg)
        or check_stop_words(listing.get("title", ""), listing.get("description", ""), cfg)
        or check_seller(listing, cfg)
    )


def reason_title(reason: str | None) -> str:
    if not reason:
        return ""
    code, _, detail = reason.partition(":")
    title = REASON_TITLES.get(code, code)
    return f"{title} ({detail})" if detail else title
