import pytest

from bot.config import Config
from bot.replies import AGREED, COUNTER, REFUSED, REPLIED, UNCLEAR, classify, find_amount

CFG = Config()
AGREE = CFG.words("replies.agree_words")
REFUSE = CFG.words("replies.refuse_words")
OFFER = 58000

CASES = [
    # согласие
    ("Да", AGREED),
    ("да, давайте", AGREED),
    ("Согласен", AGREED),
    ("Согласна, когда сможете?", AGREED),
    ("Договорились", AGREED),
    ("Ок", AGREED),
    ("окей, жду", AGREED),
    ("Давайте", AGREED),
    ("Приезжайте завтра после 19", AGREED),
    ("Забирайте", AGREED),
    ("Можно", AGREED),
    ("Устраивает", AGREED),
    ("Пойдёт", AGREED),
    ("Подходит, пишите адрес", AGREED),
    ("Да, давайте, приезжайте завтра", AGREED),
    ("Да, за 58 000 забирайте", AGREED),
    # отказ
    ("Нет", REFUSED),
    ("Не отдам", REFUSED),
    ("Мало", REFUSED),
    ("Без торга", REFUSED),
    ("Не интересно", REFUSED),
    ("Продан", REFUSED),
    ("Уже продано", REFUSED),
    ("Не договоримся", REFUSED),
    ("Не подходит", REFUSED),
    ("нет, не устраивает", REFUSED),
    ("Это не устраивает", REFUSED),
    ("Не актуально", REFUSED),
    # торг
    ("Давайте за 60, сегодня после 19 могу", COUNTER),
    ("Меньше 62000 не отдам", COUNTER),
    ("Могу за 60 000", COUNTER),
    ("61к и забирайте", COUNTER),
    ("За 63 тыс отдам", COUNTER),
    ("Нет, только за 65.000", COUNTER),
    # неясно — и согласие, и отказ
    ("да нет наверное", UNCLEAR),
    ("Можно, но мало", UNCLEAR),
    # обычный ответ
    ("Здравствуйте, а вы где находитесь?", REPLIED),
    ("Какой у вас район?", REPLIED),
    ("Позвоните мне в 19:00", REPLIED),
]


@pytest.mark.parametrize("text,kind", CASES)
def test_classify(text, kind):
    assert classify(text, AGREE, REFUSE, offer=OFFER).kind == kind


def test_amounts():
    assert find_amount("давайте за 60") == 60000
    assert find_amount("62 000 ₽") == 62000
    assert find_amount("62000") == 62000
    assert find_amount("61к") == 61000
    assert find_amount("61,5к") == 61500
    assert find_amount("после 19:00") is None
    assert find_amount("звоните +7 916 123-45-67") is None
    assert find_amount("за 15 минут подъеду") is None


def test_counter_amount_value():
    r = classify("Давайте за 60, сегодня после 19 могу", AGREE, REFUSE, offer=OFFER)
    assert r.amount == 60000
