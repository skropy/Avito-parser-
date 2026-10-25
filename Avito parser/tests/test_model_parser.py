import pytest

from bot.pricing.model_parser import (
    ModelMatcher, find_memory, memory_label, model_key, parse_listing, parse_memory_cell,
)

MODELS = [
    "iPhone 13 mini", "iPhone 13", "iPhone 13 Pro", "iPhone 13 Pro Max",
    "iPhone 14", "iPhone 14 Plus", "iPhone 14 Pro", "iPhone 14 Pro Max",
    "iPhone 15", "iPhone 15 Plus", "iPhone 15 Pro", "iPhone 15 Pro Max",
    "iPhone 16", "iPhone 16 Plus", "iPhone 16 Pro", "iPhone 16 Pro Max",
]
MATCHER = ModelMatcher({model_key(m): m for m in MODELS})

# (заголовок, ожидаемый ключ модели, ожидаемая память)
GOOD = [
    ("iPhone 15 Pro Max 256GB", "15 pro max", 256),
    ("iPhone 15 Pro Max 256 ГБ натуральный титан", "15 pro max", 256),
    ("Айфон 13 про макс 128 гб", "13 pro max", 128),
    ("Apple iPhone 14 Pro, 128 ГБ", "14 pro", 128),
    ("iPhone 14 Pro 128gb Deep Purple", "14 pro", 128),
    ("iPhone 15 256 Gb", "15", 256),
    ("iPhone 15, 128 ГБ, черный", "15", 128),
    ("iPhone 16 Pro Max 1тб", "16 pro max", 1024),
    ("iPhone 16 Pro Max 1 ТБ", "16 pro max", 1024),
    ("iPhone 16 Pro Max 1TB Desert Titanium", "16 pro max", 1024),
    ("iPhone 13 mini 128", "13 mini", 128),
    ("Айфон 13 мини 256гб", "13 mini", 256),
    ("iPhone 15Pro 128Gb", "15 pro", 128),
    ("iPhone 15 ProMax 512gb", "15 pro max", 512),
    ("iphone 14 promax 256", "14 pro max", 256),
    ("iPhone 14 Pro-Max 128 гб", "14 pro max", 128),
    ("Apple iPhone 14 Plus 128 ГБ, синий", "14 plus", 128),
    ("iPhone 14 плюс 128", "14 plus", 128),
    ("iPhone 15 Plus 256 гб", "15 plus", 256),
    ("Айфон 15 плюс 128гб", "15 plus", 128),
    ("iPhone 16 128GB ultramarine", "16", 128),
    ("iPhone 16 Pro 256 ГБ", "16 pro", 256),
    ("Айфон 16 про 128", "16 pro", 128),
    ("iPhone 13 128 ГБ", "13", 128),
    ("Iphone 13 256gb идеал", "13", 256),
    ("IPHONE 13 PRO 128GB", "13 pro", 128),
    ("iPhone 13 Pro 1тб", "13 pro", 1024),
    ("iPhone 15 Pro 256 100%", "15 pro", 256),
    ("iPhone 15 Pro 128 акб 89%", "15 pro", 128),
    ("Телефон iPhone 14 128GB", "14", 128),
    ("Смартфон Apple iPhone 15 Pro Max 256 ГБ eSIM", "15 pro max", 256),
    ("iPhone 14 Pro max 512gb", "14 pro max", 512),
    ("Айфон 14 про 256 гигабайт", "14 pro", 256),
    ("iPhone 15 про макс 256гб", "15 pro max", 256),
    ("iPhone 16 Plus 128 гб розовый", "16 plus", 128),
    ("iPhone 13 Pro Max 128Gb Sierra Blue", "13 pro max", 128),
    ("айфон 14 128", "14", 128),
    ("iPhone 15 128gb 2023 года", "15", 128),
    ("Продаю iPhone 16 Pro Max 256 в отличном состоянии", "16 pro max", 256),
    ("iPhone15 Pro 256гб", "15 pro", 256),
    ("iPhone 14 pro 128 гб, 25 циклов", "14 pro", 128),
    ("iPhone 15 pm 256", "15 pro max", 256),
]


@pytest.mark.parametrize("title,key,mem", GOOD)
def test_good_titles(title, key, mem):
    r = parse_listing(title, "", MATCHER)
    assert (r.model_key, r.memory, r.reason) == (key, mem, None)


# Модель или память не определяются однозначно — объявление пропускается
BAD = [
    ("iPhone 13 / 14 128", "model"),
    ("iPhone 13 Pro / Pro Max 128", "model"),
    ("iPhone 15 Pro 128/256", "memory"),
    ("iPhone 15 Pro", "memory"),
    ("Айфон 15 128 000 руб", "memory"),
    ("iPhone SE 2020 64gb", "model"),
    ("iPhone 12 128gb", "model"),
    ("iPhone 15 Max 256", "model"),
    ("Смартфон Samsung Galaxy S23 256", "model"),
    ("Телефон 128 ГБ", "model"),
]


@pytest.mark.parametrize("title,what", BAD)
def test_bad_titles(title, what):
    r = parse_listing(title, "", MATCHER)
    assert r.reason is not None
    assert r.reason.startswith(what)


def test_description_fallback():
    r = parse_listing("Продам телефон", "Продаю iPhone 14 Pro, память 256 гб, всё работает", MATCHER)
    assert (r.model_key, r.memory) == ("14 pro", 256)


def test_description_bare_memory_not_used():
    # в описании без «гб» число 128 не считается памятью
    r = parse_listing("iPhone 14 Pro", "отдам за 128 тысяч", MATCHER)
    assert r.memory is None


def test_title_priority_over_description():
    r = parse_listing("iPhone 13 128gb", "переходил на 15 Pro", MATCHER)
    assert r.model_key == "13"


def test_model_key():
    assert model_key("iPhone 15 Pro Max") == "15 pro max"
    assert model_key("Айфон 13 мини") == "13 mini"
    assert model_key("15 Plus") == "15 plus"
    assert model_key("iPhone 16e") == "16e"


def test_new_models_from_table():
    m = ModelMatcher({model_key(x): x for x in ["iPhone 16e", "iPhone 17 Pro", "iPhone Air", "iPhone 16"]})
    assert m.find("iPhone 16e 128gb")[0] == "16e"
    assert m.find("iPhone 16 128gb")[0] == "16"
    assert m.find("iPhone 17 Pro 256")[0] == "17 pro"
    assert m.find("Apple iPhone Air 256")[0] == "air"


def test_memory_cells():
    assert parse_memory_cell("256") == 256
    assert parse_memory_cell("256 ГБ") == 256
    assert parse_memory_cell("1 ТБ") == 1024
    assert parse_memory_cell("1TB") == 1024
    assert parse_memory_cell("1024") == 1024


def test_memory_label():
    assert memory_label(256) == "256 ГБ"
    assert memory_label(1024) == "1 ТБ"


def test_find_memory_variants():
    assert find_memory("256gb")[0] == 256
    assert find_memory("256 гб")[0] == 256
    assert find_memory("256Gb")[0] == 256
    assert find_memory("1tb")[0] == 1024
    assert find_memory("1 тб")[0] == 1024
