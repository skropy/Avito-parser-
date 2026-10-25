"""Загрузка настроек: секреты из .env, всё остальное из config.yaml."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"


class Config:
    def __init__(self, path: Path = ROOT / "config.yaml") -> None:
        self.path = Path(path)
        self.data: dict = {}
        self.reload()

    def reload(self) -> None:
        load_dotenv(ROOT / ".env", override=True)
        with open(self.path, encoding="utf-8") as f:
            self.data = yaml.safe_load(f) or {}

        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.telegram_chat_id = int(chat) if chat.lstrip("-").isdigit() else 0
        self.google_sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
        self.google_worksheet = (
            os.getenv("GOOGLE_SHEET_WORKSHEET", "").strip() or self.get("pricing.worksheet", "")
        )
        self.google_credentials_file = self.resolve(
            os.getenv("GOOGLE_CREDENTIALS_FILE", "").strip()
            or "credentials/google_service_account.json"
        )

    def get(self, dotted: str, default: Any = None) -> Any:
        """cfg.get("messaging.daily_message_limit", 30)"""
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return default if node is None else node

    def words(self, dotted: str) -> list[str]:
        return [str(w).strip() for w in (self.get(dotted, []) or []) if str(w).strip()]

    @staticmethod
    def resolve(path: str) -> Path:
        p = Path(path).expanduser()
        return p if p.is_absolute() else ROOT / p

    @property
    def dry_run(self) -> bool:
        return bool(self.get("dry_run", True))

    @property
    def timezone(self) -> str:
        return str(self.get("timezone", "Europe/Moscow"))
