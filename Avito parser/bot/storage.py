"""SQLite: просмотренные объявления, диалоги, сообщения, счётчики."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id              TEXT PRIMARY KEY,
    url             TEXT,
    title           TEXT,
    model           TEXT,
    memory          INTEGER,
    price           INTEGER,
    seller_id       TEXT,
    seller_reviews  INTEGER,
    zone            TEXT,
    filter_reason   TEXT,
    data            TEXT,
    created_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at);

CREATE TABLE IF NOT EXISTS dialogs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id       TEXT UNIQUE,
    avito_chat_id    TEXT,
    chat_url         TEXT,
    offer            INTEGER,
    max_price        INTEGER,
    status           TEXT,
    auto             INTEGER DEFAULT 0,
    last_preview     TEXT,
    last_message_at  TEXT,
    tg_message_ids   TEXT DEFAULT '[]',
    created_at       TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dialog_id   INTEGER,
    direction   TEXT,
    text        TEXT,
    msg_key     TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_dialog ON messages(dialog_id);

CREATE TABLE IF NOT EXISTS counters (
    date            TEXT PRIMARY KEY,
    auto_sent       INTEGER DEFAULT 0,
    limit_notified  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tg_links (
    tg_message_id  INTEGER PRIMARY KEY,
    listing_id     TEXT
);

CREATE TABLE IF NOT EXISTS sellers_contacted (
    seller_id   TEXT PRIMARY KEY,
    listing_id  TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
"""

ACTIVE_STATUSES = ("sent", "replied", "counter", "agreed")


class Storage:
    def __init__(self, path: Path, tz: str = "Europe/Moscow") -> None:
        self.path = Path(path)
        self.tz = ZoneInfo(tz)
        self.db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------ служебное
    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript(SCHEMA)
        await self.db.commit()

    async def close(self) -> None:
        if self.db:
            await self.db.close()

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def now_iso(self) -> str:
        return self.now().isoformat(timespec="seconds")

    def today(self) -> str:
        return self.now().date().isoformat()

    async def _one(self, sql: str, args: tuple = ()) -> aiosqlite.Row | None:
        async with self.db.execute(sql, args) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, args: tuple = ()) -> list[aiosqlite.Row]:
        async with self.db.execute(sql, args) as cur:
            return list(await cur.fetchall())

    # ------------------------------------------------------------------ kv
    async def kv_get(self, key: str, default: str | None = None) -> str | None:
        row = await self._one("SELECT value FROM kv WHERE key=?", (key,))
        return row["value"] if row else default

    async def kv_set(self, key: str, value: str) -> None:
        await self.db.execute("INSERT OR REPLACE INTO kv(key, value) VALUES(?, ?)", (key, value))
        await self.db.commit()

    # ------------------------------------------------------------ listings
    async def is_known(self, listing_id: str) -> bool:
        return await self._one("SELECT 1 FROM listings WHERE id=?", (listing_id,)) is not None

    async def mark_seen(self, items: list[dict]) -> None:
        now = self.now_iso()
        await self.db.executemany(
            "INSERT OR IGNORE INTO listings(id, url, title, price, filter_reason, created_at) "
            "VALUES(?, ?, ?, ?, 'first_run', ?)",
            [(i["id"], i.get("url"), i.get("title"), i.get("price"), now) for i in items],
        )
        await self.db.commit()

    async def save_listing(self, data: dict) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO listings(id, url, title, model, memory, price, seller_id, "
            "seller_reviews, zone, filter_reason, data, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM listings WHERE id=?), ?))",
            (
                data["id"], data.get("url"), data.get("title"), data.get("model_name"),
                data.get("memory"), data.get("price"), data.get("seller_id"),
                data.get("seller_reviews"), data.get("zone"), data.get("filter_reason"),
                json.dumps(data, ensure_ascii=False), data["id"], self.now_iso(),
            ),
        )
        await self.db.commit()

    async def get_listing(self, listing_id: str) -> dict | None:
        row = await self._one("SELECT data FROM listings WHERE id=?", (listing_id,))
        if not row or not row["data"]:
            return None
        return json.loads(row["data"])

    # ------------------------------------------------------------- dialogs
    async def get_dialog(self, listing_id: str) -> dict | None:
        row = await self._one("SELECT * FROM dialogs WHERE listing_id=?", (listing_id,))
        return dict(row) if row else None

    async def get_dialog_by_id(self, dialog_id: int) -> dict | None:
        row = await self._one("SELECT * FROM dialogs WHERE id=?", (dialog_id,))
        return dict(row) if row else None

    async def create_dialog(self, listing_id: str, chat_id: str | None, chat_url: str | None,
                            offer: int | None, max_price: int | None, status: str,
                            auto: bool, seller_id: str | None) -> int:
        now = self.now_iso()
        cur = await self.db.execute(
            "INSERT OR IGNORE INTO dialogs(listing_id, avito_chat_id, chat_url, offer, max_price, status, "
            "auto, last_message_at, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (listing_id, chat_id, chat_url, offer, max_price, status, int(auto), now, now),
        )
        if seller_id:
            await self.db.execute(
                "INSERT OR IGNORE INTO sellers_contacted(seller_id, listing_id, created_at) VALUES(?, ?, ?)",
                (seller_id, listing_id, now),
            )
        await self.db.commit()
        if cur.rowcount == 1 and cur.lastrowid:
            return cur.lastrowid
        row = await self._one("SELECT id FROM dialogs WHERE listing_id=?", (listing_id,))
        return row["id"]

    async def update_dialog(self, dialog_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        await self.db.execute(f"UPDATE dialogs SET {cols} WHERE id=?", (*fields.values(), dialog_id))
        await self.db.commit()

    async def seller_contacted(self, seller_id: str | None) -> bool:
        if not seller_id:
            return False
        return await self._one("SELECT 1 FROM sellers_contacted WHERE seller_id=?", (seller_id,)) is not None

    async def active_dialogs(self, days: int) -> list[dict]:
        since = (self.now() - timedelta(days=days)).isoformat(timespec="seconds")
        marks = ",".join("?" * len(ACTIVE_STATUSES))
        rows = await self._all(
            f"SELECT * FROM dialogs WHERE status IN ({marks}) AND chat_url IS NOT NULL "
            f"AND last_message_at >= ? ORDER BY last_message_at DESC",
            (*ACTIVE_STATUSES, since),
        )
        return [dict(r) for r in rows]

    async def deals(self) -> list[dict]:
        rows = await self._all(
            "SELECT d.*, l.data AS listing_data, "
            "(SELECT m.text FROM messages m WHERE m.dialog_id = d.id AND m.direction = 'in' "
            " ORDER BY m.id DESC LIMIT 1) AS last_in "
            "FROM dialogs d LEFT JOIN listings l ON l.id = d.listing_id "
            "WHERE d.status IN ('agreed', 'counter') ORDER BY d.last_message_at DESC LIMIT 30"
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ messages
    async def add_message(self, dialog_id: int, direction: str, text: str, key: str | None = None) -> None:
        now = self.now_iso()
        await self.db.execute(
            "INSERT INTO messages(dialog_id, direction, text, msg_key, created_at) VALUES(?, ?, ?, ?, ?)",
            (dialog_id, direction, text, key, now),
        )
        await self.db.execute("UPDATE dialogs SET last_message_at=? WHERE id=?", (now, dialog_id))
        await self.db.commit()

    async def message_keys(self, dialog_id: int) -> set[str]:
        rows = await self._all("SELECT msg_key FROM messages WHERE dialog_id=? AND msg_key IS NOT NULL",
                               (dialog_id,))
        return {r["msg_key"] for r in rows}

    async def outgoing_texts(self, dialog_id: int) -> list[str]:
        rows = await self._all("SELECT text FROM messages WHERE dialog_id=? AND direction='out'", (dialog_id,))
        return [r["text"] for r in rows]

    # ------------------------------------------------- связь Telegram ↔ лот
    async def link_tg(self, tg_message_ids: list[int], listing_id: str) -> None:
        await self.db.executemany(
            "INSERT OR REPLACE INTO tg_links(tg_message_id, listing_id) VALUES(?, ?)",
            [(mid, listing_id) for mid in tg_message_ids],
        )
        dialog = await self.get_dialog(listing_id)
        if dialog:
            ids = json.loads(dialog.get("tg_message_ids") or "[]") + list(tg_message_ids)
            await self.db.execute("UPDATE dialogs SET tg_message_ids=? WHERE id=?",
                                  (json.dumps(ids[-50:]), dialog["id"]))
        await self.db.commit()

    async def listing_by_tg(self, tg_message_id: int) -> str | None:
        row = await self._one("SELECT listing_id FROM tg_links WHERE tg_message_id=?", (tg_message_id,))
        return row["listing_id"] if row else None

    # ------------------------------------------------------------ счётчики
    async def auto_sent_today(self) -> int:
        row = await self._one("SELECT auto_sent FROM counters WHERE date=?", (self.today(),))
        return row["auto_sent"] if row else 0

    async def inc_auto_sent(self) -> None:
        await self.db.execute(
            "INSERT INTO counters(date, auto_sent) VALUES(?, 1) "
            "ON CONFLICT(date) DO UPDATE SET auto_sent = auto_sent + 1",
            (self.today(),),
        )
        await self.db.commit()

    async def limit_notified_today(self) -> bool:
        row = await self._one("SELECT limit_notified FROM counters WHERE date=?", (self.today(),))
        return bool(row and row["limit_notified"])

    async def set_limit_notified(self) -> None:
        await self.db.execute(
            "INSERT INTO counters(date, limit_notified) VALUES(?, 1) "
            "ON CONFLICT(date) DO UPDATE SET limit_notified = 1",
            (self.today(),),
        )
        await self.db.commit()

    # ----------------------------------------------------------- статистика
    async def stats(self, days: int) -> dict:
        start = self.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        since = start.isoformat(timespec="seconds")
        found = await self._one(
            "SELECT COUNT(*) AS n FROM listings WHERE created_at >= ? AND COALESCE(filter_reason,'') != 'first_run'",
            (since,),
        )
        reasons = await self._all(
            "SELECT filter_reason AS r, COUNT(*) AS n FROM listings WHERE created_at >= ? "
            "AND filter_reason IS NOT NULL AND filter_reason != 'first_run' GROUP BY filter_reason",
            (since,),
        )
        zones = await self._all(
            "SELECT zone AS z, COUNT(*) AS n FROM listings WHERE created_at >= ? AND zone IS NOT NULL GROUP BY zone",
            (since,),
        )
        written = await self._one(
            "SELECT COUNT(*) AS n, SUM(auto) AS a, SUM(status='dry_run') AS dry FROM dialogs WHERE created_at >= ?",
            (since,),
        )
        replied = await self._one(
            "SELECT COUNT(DISTINCT d.id) AS n FROM dialogs d JOIN messages m ON m.dialog_id = d.id "
            "WHERE d.created_at >= ? AND m.direction = 'in'",
            (since,),
        )
        agreed = await self._one(
            "SELECT COUNT(*) AS n FROM dialogs WHERE created_at >= ? AND status = 'agreed'", (since,)
        )
        grouped: dict[str, int] = {}
        for r in reasons:
            key = (r["r"] or "").split(":")[0]
            grouped[key] = grouped.get(key, 0) + r["n"]
        return {
            "found": found["n"],
            "reasons": grouped,
            "zones": {r["z"]: r["n"] for r in zones},
            "written": written["n"] or 0,
            "written_auto": written["a"] or 0,
            "written_dry": written["dry"] or 0,
            "replied": replied["n"] or 0,
            "agreed": agreed["n"] or 0,
        }
