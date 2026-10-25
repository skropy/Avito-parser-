"""Определение модели iPhone и объёма памяти по заголовку/описанию.

Список моделей не зашит в код — он приходит из таблицы цен. Каждое название
из таблицы («iPhone 15 Pro Max») превращается в ключ «15 pro max», и по
ключу строится шаблон поиска.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from bot.textutil import normalize

L = "a-zа-яё"


def _w(word: str) -> str:
    """Слово, не являющееся частью другого слова (цифры рядом допускаются)."""
    return rf"(?<![{L}]){word}(?![{L}])"


# Русские и слитные написания → единый вид. Порядок важен.
_SYNONYMS: list[tuple[str, str]] = [
    (rf"(?<![{L}])(?:айфон|айфоне|айфона|айфончик|iphone|i-phone|ifone)(?![{L}])", " iphone "),
    (rf"(?<![{L}])apple(?![{L}])", " "),
    (_w(r"(?:pro|про)\s*-?\s*(?:max|макс)") + "|" + _w("promax") + "|" + _w("промакс") + "|" + _w("pm"), " pro max "),
    (_w("про"), " pro "),
    (_w("плюс"), " plus "),
    (_w("мини"), " mini "),
    (_w("макс"), " max "),
    (_w("эир") + "|" + _w("эйр"), " air "),
    (r"(?<=\d)\s*[eе](?![{L}])".format(L=L), "e "),
    # «15pro», «14plus» → «15 pro», «14 plus»
    (r"(?<=\d)(?=(?:pro|plus|mini|max)(?![a-z]))", " "),
]

_VARIANTS = r"(?:pro|plus|mini|max|e(?![a-z]))"
_ALT_RE = re.compile(
    rf"\s*(?:/|\\|или|либо|,)\s*(?:iphone\s*)?(?:(1\d|2\d)(?!\d)(?!\s*(?:gb|гб|%|цикл|год|г(?![а-я])|мин|дн|час|шт))|({_VARIANTS}))"
)


def normalize_title(text: str) -> str:
    text = normalize(text)
    for pattern, repl in _SYNONYMS:
        text = re.sub(pattern, repl, text)
    return re.sub(r"\s+", " ", text).strip()


def model_key(name: str) -> str:
    """«iPhone 15 Pro Max» → «15 pro max», «iPhone 16e» → «16e»."""
    text = normalize_title(name)
    text = re.sub(r"\biphone\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _key_pattern(key: str) -> re.Pattern:
    tokens = key.split(" ")
    body = r"\s*".join(re.escape(t) for t in tokens)
    has_digits = any(ch.isdigit() for ch in key)
    only_number = key.isdigit()
    if only_number:
        # голое «15» — только после слова iphone и без «pro/plus/…» следом
        pat = rf"iphone\s*(?<!\d){body}(?!\d)(?!\s*{_VARIANTS})"
    elif not has_digits:
        pat = rf"iphone\s*{body}(?![a-z0-9])"
    else:
        pat = rf"(?:iphone\s*)?(?<!\d){body}(?![a-z0-9])"
    return re.compile(pat)


@dataclass
class ModelMatcher:
    """Строится по списку моделей из таблицы: {ключ: красивое название}."""
    models: dict[str, str]

    def __post_init__(self) -> None:
        self._patterns = [(k, _key_pattern(k)) for k in self.models if k]

    def find(self, text: str) -> tuple[str | None, bool]:
        """Возвращает (ключ, неоднозначно?)."""
        norm = normalize_title(text)
        spans: list[tuple[int, int, str]] = []
        for key, pat in self._patterns:
            for m in pat.finditer(norm):
                spans.append((m.start(), m.end(), key))
        spans.sort(key=lambda s: s[1] - s[0], reverse=True)
        taken: list[tuple[int, int, str]] = []
        for s in spans:
            if all(s[1] <= t[0] or s[0] >= t[1] for t in taken):
                taken.append(s)
        keys = {t[2] for t in taken}
        # «iPhone 13 / 14», «iPhone 13 Pro / Pro Max» — перечисление моделей
        for start, end, key in taken:
            m = _ALT_RE.match(norm, end)
            if m and (m.group(2) or m.group(1) != key.split(" ")[0]):
                return None, True
        if len(keys) == 1:
            return keys.pop(), False
        return None, len(keys) > 1


_TB = re.compile(r"(?<![\d.,])([12])\s*(?:tb|тб|терабайт[а-я]*|tera\w*)(?![a-zа-я])")
_GB_UNIT = re.compile(
    r"(?<![\d.,])(32|64|128|256|512|1000|1024)\s*(?:gb|гб|g|г|гиг[а-я]*|gig[a-z]*)(?![a-zа-я])"
)
# «256» без единиц — но не «128 000 ₽», не «256%» и не «512 тыс»
_GB_BARE = re.compile(
    r"(?<![\d.,])(64|128|256|512)(?![\d.,%])(?!\s?\d{3}(?!\d)(?!\s*%))"
    r"(?!\s*(?:₽|руб|р(?![а-я])|тыс|k(?![a-z])|к(?![а-я])|%))"
)


def find_memory(text: str, allow_bare: bool = True) -> tuple[int | None, bool]:
    """Объём в ГБ (1 ТБ = 1024). Возвращает (объём, неоднозначно?)."""
    norm = normalize_title(text)
    values: set[int] = set()
    for m in _TB.finditer(norm):
        values.add(int(m.group(1)) * 1024)
    for m in _GB_UNIT.finditer(norm):
        v = int(m.group(1))
        values.add(1024 if v in (1000, 1024) else v)
    if allow_bare and not values:
        for m in _GB_BARE.finditer(norm):
            values.add(int(m.group(1)))
    if len(values) == 1:
        return values.pop(), False
    return None, len(values) > 1


def parse_memory_cell(cell: str) -> int | None:
    """Ячейка таблицы: «256», «256 ГБ», «1 ТБ», «1024»."""
    text = normalize(str(cell))
    mem, _ = find_memory(text, allow_bare=True)
    if mem:
        return mem
    digits = re.sub(r"\D", "", text)
    if digits in ("1", "2") and ("т" in text or "t" in text):
        return int(digits) * 1024
    if digits.isdigit() and int(digits) in (32, 64, 128, 256, 512, 1024, 2048):
        return int(digits)
    if digits == "1000":
        return 1024
    return None


def memory_label(gb: int | None) -> str:
    if not gb:
        return "?"
    if gb >= 1024:
        return f"{gb // 1024} ТБ"
    return f"{gb} ГБ"


@dataclass
class ParseResult:
    model_key: str | None
    memory: int | None
    reason: str | None  # почему не удалось


def parse_listing(title: str, description: str, matcher: ModelMatcher) -> ParseResult:
    key, ambiguous = matcher.find(title)
    if not key and not ambiguous:
        key, ambiguous = matcher.find(description or "")
    mem, mem_ambiguous = find_memory(title, allow_bare=True)
    if not mem and not mem_ambiguous:
        mem, mem_ambiguous = find_memory(description or "", allow_bare=False)

    if not key:
        return ParseResult(None, mem, "model_ambiguous" if ambiguous else "model_unknown")
    if not mem:
        return ParseResult(key, None, "memory_ambiguous" if mem_ambiguous else "memory_unknown")
    return ParseResult(key, mem, None)
