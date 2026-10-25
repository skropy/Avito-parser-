"""Таблица цен скупки: Google Таблица (или локальный CSV), кэш, перечитывание."""
from __future__ import annotations

import asyncio
import csv
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from bot.config import Config
from bot.pricing.model_parser import ModelMatcher, model_key, parse_memory_cell
from bot.textutil import normalize, parse_price


@dataclass
class PriceRow:
    model: str          # как в таблице: «iPhone 15 Pro»
    key: str            # «15 pro»
    memory: int         # ГБ
    buy: int            # цена скупки
    market: int | None  # средняя цена на рынке
    sell: int | None    # цена продажи
    profit: int | None  # чистая прибыль


# какие слова ищем в заголовках колонок
_COLUMNS = {
    "model": ("модель",),
    "memory": ("память", "объем", "объём"),
    "buy": ("скупк",),
    "market": ("рынк", "рынок", "средн"),
    "sell": ("продаж",),
    "profit": ("прибыл",),
}


def parse_rows(rows: list[list[str]]) -> list[PriceRow]:
    if not rows:
        return []
    header = [normalize(c) for c in rows[0]]
    idx: dict[str, int] = {}
    for name, needles in _COLUMNS.items():
        for i, h in enumerate(header):
            if any(n in h for n in needles) and i not in idx.values():
                idx[name] = i
                break
    # если заголовки не распознаны — берём колонки по порядку
    for pos, name in enumerate(("model", "memory", "buy", "market", "sell", "profit")):
        idx.setdefault(name, pos)

    result: list[PriceRow] = []
    for raw in rows[1:]:
        cells = list(raw) + [""] * 6

        def cell(name: str) -> str:
            return str(cells[idx[name]]).strip()

        name = cell("model")
        if not name:
            continue
        key = model_key(name)
        memory = parse_memory_cell(cell("memory"))
        buy = parse_price(cell("buy"))
        if not key or not memory or not buy:
            logger.debug("Строка таблицы пропущена: {}", raw)
            continue
        result.append(PriceRow(
            model=name, key=key, memory=memory, buy=buy,
            market=parse_price(cell("market")), sell=parse_price(cell("sell")),
            profit=parse_price(cell("profit")),
        ))
    return result


class PriceTable:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.rows: dict[tuple[str, int], PriceRow] = {}
        self.models: dict[str, str] = {}
        self.matcher = ModelMatcher({})
        self.loaded_at: float = 0.0
        self.source = ""
        self.last_error: str | None = None

    @property
    def is_loaded(self) -> bool:
        return bool(self.rows)

    def get(self, key: str, memory: int) -> PriceRow | None:
        return self.rows.get((key, memory))

    def due(self) -> bool:
        return time.time() - self.loaded_at >= float(self.cfg.get("pricing.refresh_sec", 300))

    async def refresh(self) -> None:
        """Перечитать таблицу. При ошибке старый кэш остаётся, ошибка пробрасывается."""
        try:
            rows, source = await asyncio.to_thread(self._load_raw)
            parsed = parse_rows(rows)
            if not parsed:
                raise ValueError("в таблице не найдено ни одной корректной строки")
        except Exception as e:
            self.last_error = str(e) or e.__class__.__name__
            self.loaded_at = time.time()  # следующую попытку — через refresh_sec
            raise
        self.rows = {(r.key, r.memory): r for r in parsed}
        self.models = {}
        for r in parsed:
            self.models.setdefault(r.key, _display_name(r.model))
        self.matcher = ModelMatcher(self.models)
        self.loaded_at = time.time()
        self.source = source
        self.last_error = None
        logger.info("Таблица цен загружена ({}): {} строк, {} моделей", source, len(parsed), len(self.models))

    def _load_raw(self) -> tuple[list[list[str]], str]:
        if self.cfg.google_sheet_id:
            import gspread

            creds = self.cfg.google_credentials_file
            if not Path(creds).exists():
                raise FileNotFoundError(f"нет файла ключа Google: {creds}")
            gc = gspread.service_account(filename=str(creds))
            sh = gc.open_by_key(self.cfg.google_sheet_id)
            ws = sh.worksheet(self.cfg.google_worksheet) if self.cfg.google_worksheet else sh.sheet1
            return ws.get_all_values(), "Google Таблица"
        path = self.cfg.resolve(str(self.cfg.get("pricing.local_csv", "prices_example.csv")))
        with open(path, encoding="utf-8-sig", newline="") as f:
            sample = f.read(2048)
            f.seek(0)
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            return [row for row in csv.reader(f, dialect)], f"CSV {path.name}"


def _display_name(name: str) -> str:
    name = " ".join(name.split())
    if not normalize(name).startswith(("iphone", "айфон")):
        name = "iPhone " + name
    return name
