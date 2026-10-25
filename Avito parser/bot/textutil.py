"""Общие помощники для работы с текстом: нормализация, поиск слов, числа."""
from __future__ import annotations

import re

LETTER = "a-zа-яё"
NEGATIONS = ("не", "без", "нет", "ни")


def normalize(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = text.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def phrase_pattern(phrase: str) -> re.Pattern:
    """Короткие слова (до 3 букв) — целиком, длинные — по началу слова."""
    phrase = normalize(phrase)
    body = r"\s+".join(re.escape(p) for p in phrase.split(" "))
    tail = rf"(?![{LETTER}0-9])" if len(phrase) <= 3 else ""
    return re.compile(rf"(?<![{LETTER}0-9]){body}{tail}")


def find_phrases(text: str, phrases: list[str], respect_negation: bool = True) -> list[str]:
    """Какие фразы из списка встречаются в тексте (text уже нормализован).

    Если respect_negation, совпадение, перед которым стоит «не/без/нет/ни»,
    не считается (кроме фраз, которые сами начинаются с отрицания).
    """
    found = []
    for phrase in phrases:
        norm = normalize(phrase)
        if not norm:
            continue
        starts_negated = norm.split(" ")[0] in NEGATIONS
        for m in phrase_pattern(norm).finditer(text):
            if respect_negation and not starts_negated and is_negated(text, m.start()):
                continue
            found.append(phrase)
            break
    return found


def is_negated(text: str, pos: int) -> bool:
    before = re.findall(rf"[{LETTER}]+", text[max(0, pos - 12):pos])
    return bool(before) and before[-1] in NEGATIONS


def remove_phrases(text: str, phrases: list[str]) -> str:
    for phrase in phrases:
        norm = normalize(phrase)
        if norm:
            text = phrase_pattern(norm).sub(" ", text)
    return text


def parse_price(raw: str | int | float | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    digits = re.sub(r"[^\d]", "", str(raw).split(",")[0].split(".")[0])
    return int(digits) if digits else None


def fmt_rub(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", " ") + " ₽"


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many
