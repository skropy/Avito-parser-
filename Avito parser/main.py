"""Точка входа: python main.py"""
from __future__ import annotations

import asyncio
import fcntl
import signal
import sys

from loguru import logger

from bot.config import DATA_DIR, Config
from bot.log import setup_logging


def acquire_single_instance_lock():
    """Не даём запустить две копии бота одновременно (они бы делили один профиль браузера)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = open(DATA_DIR / "bot.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.error("Бот уже запущен в другом окне или через автозапуск. Вторая копия не нужна.")
        sys.exit(0)
    return f


def check_config(cfg: Config) -> list[str]:
    problems = []
    if not cfg.telegram_token:
        problems.append("в .env не заполнен TELEGRAM_BOT_TOKEN")
    if not cfg.telegram_chat_id:
        problems.append("в .env не заполнен TELEGRAM_CHAT_ID (узнать: python scripts/get_chat_id.py)")
    if cfg.google_sheet_id and not cfg.google_credentials_file.exists():
        problems.append(f"не найден файл ключа Google: {cfg.google_credentials_file}")
    if not cfg.get("search.search_url"):
        problems.append("в config.yaml не задан search.search_url")
    return problems


async def main() -> int:
    cfg = Config()
    problems = check_config(cfg)
    if problems:
        for p in problems:
            logger.error("Настройка: {}", p)
        logger.error("Исправьте файл .env / config.yaml и запустите бота снова.")
        return 0  # код 0 — чтобы автозапуск не перезапускал бота по кругу

    from bot.scheduler import App  # импорт здесь, чтобы ошибки настройки показывались раньше

    app = App(cfg)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    run_task = asyncio.create_task(app.run())
    stop_task = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait({run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    code = 0
    if run_task in done:
        exc = run_task.exception()
        if exc:
            logger.opt(exception=exc).critical("Бот упал")
            code = 1
    else:
        logger.info("Останавливаюсь…")
        run_task.cancel()
        try:
            await run_task
        except BaseException:
            pass
    stop_task.cancel()
    await app.shutdown()
    logger.info("Бот остановлен")
    return code


if __name__ == "__main__":
    setup_logging()
    lock = acquire_single_instance_lock()
    sys.exit(asyncio.run(main()))
