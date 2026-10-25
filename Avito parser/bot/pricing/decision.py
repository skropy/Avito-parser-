"""Зоны цен и расчёт предложения."""
from __future__ import annotations

from dataclasses import dataclass

from bot.pricing.sheet import PriceRow

HOT, AUTO, WATCH = "hot", "auto", "watch"
ZONE_ICONS = {HOT: "🔥", AUTO: "✅", WATCH: "👀"}


@dataclass
class Decision:
    zone: str | None      # hot / auto / watch / None (игнор)
    offer: int            # сколько предлагаем
    pct: float            # на сколько % цена выше скупки
    profit: int | None    # цена продажи − предложение
    max_price: int        # мой максимум (скупка × 1.25)


def round_down(value: float, step: int) -> int:
    step = int(step or 1)
    return int(value // step * step)


def decide(price: int, row: PriceRow, auto_pct: float = 25, notify_pct: float = 40,
           hot_discount: int = 0, round_to: int = 500) -> Decision:
    buy = row.buy
    pct = (price / buy - 1) * 100 if buy else 0.0
    max_price = int(buy * (1 + auto_pct / 100))

    if price <= buy:
        zone = HOT
        offer = price - hot_discount
        if hot_discount:
            offer = round_down(offer, round_to)
    elif price <= buy * (1 + auto_pct / 100):
        zone, offer = AUTO, round_down(buy, round_to)
    elif price <= buy * (1 + notify_pct / 100):
        zone, offer = WATCH, round_down(buy, round_to)
    else:
        zone, offer = None, round_down(buy, round_to)

    profit = row.sell - offer if row.sell else None
    return Decision(zone=zone, offer=offer, pct=pct, profit=profit, max_price=max_price)
