"""Тексты уведомлений (HTML-разметка Telegram)."""
from __future__ import annotations

from html import escape

from bot.filters import REASON_TITLES
from bot.pricing.decision import HOT, ZONE_ICONS
from bot.textutil import fmt_rub, plural


def _name(l: dict) -> str:
    return escape(f"{l.get('model_name', l.get('title', ''))} {l.get('memory_label', '')}".strip())


def _seller_line(l: dict) -> str:
    parts = [escape(l.get("seller_name") or "продавец")]
    if l.get("seller_rating"):
        parts.append(f"★{l['seller_rating']}")
    n = l.get("seller_reviews")
    if n is not None:
        parts.append(f"{n} {plural(n, 'отзыв', 'отзыва', 'отзывов')}")
    return "👤 " + " · ".join(parts)


def _place(l: dict) -> str:
    if l.get("metro"):
        return "📍 м. " + escape(", ".join(l["metro"]))
    if l.get("address"):
        return "📍 " + escape(l["address"][:80])
    return ""


def _common_tail(l: dict) -> list[str]:
    lines = [_seller_line(l)]
    place = _place(l)
    if place:
        lines.append(place)
    if l.get("battery"):
        lines.append(f"🔋 АКБ: {l['battery']}% (из описания)")
    lines.append(f"🔗 {escape(l['url'])}")
    return lines


def written_card(l: dict, text: str, dry_run: bool, manual: bool = False) -> str:
    icon = "✋" if manual else ZONE_ICONS.get(l.get("zone"), "✅")
    action = "написал бы продавцу" if dry_run else "написал продавцу"
    head = f"{'[DRY RUN] ' if dry_run else ''}{icon} <b>{_name(l)}</b> — {action}"
    lines = [
        head,
        f"💰 Цена объявления: {fmt_rub(l.get('price'))}",
        f"🤝 Предложил: {fmt_rub(l.get('offer'))} (скупка {fmt_rub(l.get('buy'))})",
    ]
    if l.get("profit") is not None:
        lines.append(f"📈 Ожидаемая прибыль: ~{fmt_rub(l['profit'])}")
    lines += _common_tail(l)
    lines.append(f"✉️ <i>{escape(text)}</i>")
    return "\n".join(lines)


WATCH_REASONS = {
    "zone": "зона +25–40%",
    "night": "ночное время",
    "limit": "дневной лимит",
    "autowrite_off": "автописьма выключены",
    "seller_contacted": "этому продавцу уже писали",
    "send_failed": "не получилось отправить автоматически",
}


def watch_card(l: dict, reason: str) -> str:
    zone_icon = ZONE_ICONS.get(l.get("zone"), "👀")
    head_icon = "👀" if l.get("zone") not in (HOT,) else "🔥"
    pct = l.get("pct") or 0
    sign = "+" if pct >= 0 else ""
    lines = [
        f"{head_icon} <b>{_name(l)}</b> — можно предложить",
        f"💰 Цена: {fmt_rub(l.get('price'))} ({sign}{pct:.0f}% к скупке {fmt_rub(l.get('buy'))})",
        f"🤝 Моё предложение: {fmt_rub(l.get('offer'))}",
    ]
    if l.get("profit") is not None:
        lines.append(f"📈 Прибыль при этой цене: ~{fmt_rub(l['profit'])}")
    lines += _common_tail(l)
    lines.append(f"Причина: {WATCH_REASONS.get(reason, reason)} {zone_icon}")
    return "\n".join(lines)


def reply_card(l: dict, dialog: dict, text: str, kind: str, amount: int | None) -> str:
    offer = dialog.get("offer")
    icons = {"refused": "❌ Отказ", "unclear": "❓ Неясно", "counter": "💸 Торг"}
    lines = [f"💬 <b>Ответ по {_name(l)}</b> (предлагали {fmt_rub(offer)})"]
    if kind in icons:
        lines[0] += f" · {icons[kind]}"
    lines.append(f"«{escape(text)}»")
    if kind == "counter" and amount:
        lines.append(f"💸 <b>Продавец хочет: {fmt_rub(amount)}</b> · твой максимум: {fmt_rub(dialog.get('max_price'))}")
    return "\n".join(lines)


def deal_card(l: dict, dialog: dict, text: str) -> str:
    lines = [
        "🟢🟢🟢 <b>СДЕЛКА: продавец согласен</b>",
        f"<b>{_name(l)} за {fmt_rub(dialog.get('offer'))}</b>",
        f"«{escape(text)}»",
    ]
    place = _place(l).replace("📍 ", "")
    who = escape(l.get("seller_name") or "")
    lines.append(" · ".join(x for x in (f"📍 {place}" if place else "", f"👤 {who}" if who else "") if x))
    return "\n".join(x for x in lines if x)


def stats_text(title: str, s: dict) -> str:
    lines = [f"<b>{title}</b>", f"Найдено новых: {s['found']}"]
    if s["reasons"]:
        lines.append("Отсеяно:")
        for code, n in sorted(s["reasons"].items(), key=lambda x: -x[1]):
            lines.append(f"  • {REASON_TITLES.get(code, code)}: {n}")
    z = s["zones"]
    lines.append(f"Подходящих: 🔥 {z.get('hot', 0)} · ✅ {z.get('auto', 0)} · 👀 {z.get('watch', 0)}")
    lines.append(f"Написано: {s['written']} (авто {s['written_auto']}"
                 + (f", из них DRY RUN {s['written_dry']}" if s["written_dry"] else "") + ")")
    lines.append(f"Ответили: {s['replied']}")
    lines.append(f"Согласились: {s['agreed']}")
    return "\n".join(lines)
