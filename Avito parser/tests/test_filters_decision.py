import pytest

from bot.config import Config
from bot.filters import check_listing, check_stop_words
from bot.pricing.decision import AUTO, HOT, WATCH, decide
from bot.pricing.sheet import PriceRow, parse_rows

CFG = Config()


def listing(**kw):
    base = dict(title="iPhone 15 Pro 256", description="Отличное состояние", price=60000,
                seller_type="private", seller_reviews=10, seller_active_listings=2)
    base.update(kw)
    return base


@pytest.mark.parametrize("text", [
    "iPhone 14 на запчасти", "Разбит экран", "Трещина на задней крышке", "Не включается",
    "Face ID не работает", "Залочен на icloud", "Заблокирован", "Был после воды",
    "Менял экран в ремонте", "Копия iPhone 15 Pro", "Реплика 1:1", "Нет Face ID",
])
def test_broken(text):
    assert check_stop_words(text, "", CFG) is not None


@pytest.mark.parametrize("text", [
    "Не разбит, без царапин", "Без ремонта, не вскрывался", "iCloud чистый, выйду из iCloud",
    "Никогда не был в ремонте", "Есть копия чека", "Отвязан от iCloud", "Всё работает отлично",
])
def test_not_broken(text):
    assert check_stop_words("iPhone 15 Pro", text, CFG) is None


def test_filters():
    assert check_listing(listing(), CFG) is None
    assert check_listing(listing(price=None), CFG) == "no_price"
    assert check_listing(listing(price=1), CFG) == "low_price"
    assert check_listing(listing(seller_type="company"), CFG) == "company"
    assert check_listing(listing(description="Гарантия магазина 1 год"), CFG).startswith("shop_words")
    assert check_listing(listing(description="Есть рассрочка"), CFG).startswith("shop_words")
    assert check_listing(listing(description="Продаю оптом"), CFG).startswith("shop_words")
    assert check_listing(listing(description="Оптимальный вариант"), CFG) is None
    assert check_listing(listing(seller_active_listings=12), CFG) == "too_many_listings"
    assert check_listing(listing(seller_reviews=0), CFG) == "no_reviews"
    assert check_listing(listing(seller_reviews=None), CFG) == "seller_info_missing"


ROW = PriceRow(model="iPhone 15 Pro", key="15 pro", memory=256, buy=58000,
               market=66000, sell=67000, profit=9000)


def test_zones():
    d = decide(55000, ROW)
    assert (d.zone, d.offer, d.profit) == (HOT, 55000, 12000)
    d = decide(58000, ROW)
    assert d.zone == HOT
    d = decide(62000, ROW)
    assert (d.zone, d.offer) == (AUTO, 58000)
    d = decide(72500, ROW)
    assert d.zone == AUTO
    d = decide(76000, ROW)
    assert (d.zone, d.offer) == (WATCH, 58000)
    assert round(d.pct) == 31
    d = decide(81200, ROW)
    assert d.zone == WATCH
    assert decide(82000, ROW).zone is None
    assert decide(62000, ROW).max_price == 72500


def test_hot_discount_and_rounding():
    d = decide(55300, ROW, hot_discount=1000)
    assert d.offer == 54000
    row = PriceRow("iPhone 15", "15", 128, 44300, None, 53000, None)
    assert decide(50000, row).offer == 44000


def test_parse_rows_by_header():
    rows = [
        ["Модель", "Память", "Цена скупки", "Средняя цена на рынке", "Цена продажи", "Чистая прибыль"],
        ["iPhone 15 Pro", "256 ГБ", "58 000 ₽", "66 000", "67 000", "9 000"],
        ["iPhone 16 Pro Max", "1 ТБ", "100000", "", "", ""],
        ["", "", "", "", "", ""],
        ["Итого", "", "", "", "", ""],
    ]
    parsed = parse_rows(rows)
    assert [(r.key, r.memory, r.buy, r.sell) for r in parsed] == [
        ("15 pro", 256, 58000, 67000), ("16 pro max", 1024, 100000, None),
    ]
