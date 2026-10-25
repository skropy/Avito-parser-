"""Классификация ответов продавцов по ключевым словам."""
from __future__ import annotations

import re
from dataclasses import dataclass

from bot.textutil import LETTER, find_phrases, is_negated, normalize, phrase_pattern

AGREED, REFUSED, COUNTER, UNCLEAR, REPLIED = "agreed", "refused", "counter", "unclear", "replied"


@dataclass
class ReplyClass:
    kind: str
    amount: int | None = None


# «60 000», «60000», «60.000», «60к», «60 тыс», «за 60»
_AMOUNT_RE = re.compile(
    r"(?<![\d:.,])(\d{1,3}(?:[ .]\d{3})+|\d{4,7})(?![\d:])"           # полные суммы
    r"|(?<![\d:.,])(\d{1,3}(?:[.,]\d)?)\s*(?:к|k|тыс[а-я]*|т\.?р)(?![a-zа-я])"  # 60к / 60 тыс
    rf"|(?<![{LETTER}])за\s+(\d{{2,3}})(?![\d:]|[.,]\d)(?!\s*(?:минут|мин|час|сек|%|шт|раз|руб|₽))"  # «за 60»
)


def find_amount(text: str, min_amount: int = 1000) -> int | None:
    text = normalize(text)
    # телефоны и длинные номера не трогаем
    text = re.sub(r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}", " ", text)
    best: int | None = None
    for m in _AMOUNT_RE.finditer(text):
        if m.group(1):
            value = int(re.sub(r"\D", "", m.group(1)))
        elif m.group(2):
            value = int(float(m.group(2).replace(",", ".")) * 1000)
        else:
            value = int(m.group(3)) * 1000
        if value >= min_amount and value < 10_000_000:
            best = value if best is None else max(best, value)
    return best


def classify(text: str, agree_words: list[str], refuse_words: list[str],
             offer: int | None = None, min_amount: int = 1000) -> ReplyClass:
    norm = normalize(text)

    refuse = bool(find_phrases(norm, refuse_words))
    agree = False
    for word in agree_words:
        w = normalize(word)
        for m in phrase_pattern(w).finditer(norm):
            if is_negated(norm, m.start()):
                refuse = True       # «не подходит», «не устраивает», «не договорились»
            else:
                agree = True
    # «нет, не устраивает» — отрицание учтено выше

    amount = find_amount(norm, min_amount)
    # сумма выше нашего предложения (или без слов согласия) — это торг;
    # «да, за 58 000 забирайте» при предложении 58 000 — согласие
    if amount and (offer is None or amount > offer or not agree):
        return ReplyClass(COUNTER, amount)
    if agree and refuse:
        return ReplyClass(UNCLEAR, amount)
    if agree:
        return ReplyClass(AGREED, amount)
    if refuse:
        return ReplyClass(REFUSED, amount)
    return ReplyClass(REPLIED, amount)
