"""Настройка логов: консоль + файлы в logs/ с ротацией."""
from __future__ import annotations

import sys

from loguru import logger

from bot.config import LOGS_DIR


def setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:DD.MM HH:mm:ss}</green> | <level>{level: <7}</level> | {message}")
    logger.add(LOGS_DIR / "bot.log", level="DEBUG", rotation="10 MB", retention=10,
               encoding="utf-8", enqueue=True, backtrace=True, diagnose=False)
    logger.add(LOGS_DIR / "errors.log", level="ERROR", rotation="5 MB", retention=5,
               encoding="utf-8", enqueue=True, backtrace=True, diagnose=False)
