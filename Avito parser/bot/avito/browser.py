"""Playwright (Chromium) с постоянным профилем, детект капчи и страницы входа.

Браузер всегда видимый: если Авито покажет капчу или попросит войти,
вы проходите это вручную в окне браузера на Mac. Никаких обходов капчи,
подмены отпечатков и прокси здесь нет и не будет.
"""
from __future__ import annotations

import asyncio
import random
from pathlib import Path

from loguru import logger
from playwright.async_api import BrowserContext, Error as PlaywrightError, Page, async_playwright

from bot.avito import selectors as S
from bot.config import Config, DATA_DIR

BLOCK_CAPTCHA, BLOCK_LOGIN = "captcha", "login"

_DETECT_JS = """
(S) => {
  const visible = (e) => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const any = (sels) => sels.some(s => { try { return [...document.querySelectorAll(s)].some(visible); } catch (e) { return false; } });
  const title = (document.title || '').toLowerCase();
  const head = (document.body ? document.body.innerText.slice(0, 400) : '').toLowerCase();
  if (any(S.captcha) || S.blockWords.some(w => title.includes(w) || head.includes(w))) return 'captcha';
  const url = location.href.toLowerCase();
  if (S.loginUrl.some(p => url.includes(p)) || any(S.loginForm)) return 'login';
  return null;
}
"""


class AvitoBlocked(Exception):
    """Авито показал капчу/блокировку или просит войти."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class NetworkError(Exception):
    """Страница не открылась после всех повторов."""


class LayoutError(Exception):
    """Не найден нужный элемент страницы (вероятно, изменилась вёрстка)."""


class AvitoBrowser:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.lock = asyncio.Lock()       # все действия в браузере — строго по очереди
        self._pw = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    # ------------------------------------------------------------- запуск
    async def start(self) -> None:
        profile = self.cfg.resolve(str(self.cfg.get("browser.profile_dir", "data/browser_profile")))
        profile.mkdir(parents=True, exist_ok=True)
        if self._pw is None:
            self._pw = await async_playwright().start()
        logger.info("Запускаю браузер, профиль: {}", profile)
        self.context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            locale="ru-RU",
            timezone_id=self.cfg.timezone,
            viewport={"width": 1280, "height": 860},
            args=["--start-maximized"],
        )
        timeout = int(self.cfg.get("browser.navigation_timeout_sec", 45)) * 1000
        self.context.set_default_timeout(timeout)
        self.context.set_default_navigation_timeout(timeout)
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def stop(self) -> None:
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self.context = self.page = None
        self._pw = None

    async def ensure_alive(self) -> Page:
        """Если окно браузера закрыли — открываем заново."""
        alive = False
        if self.context and self.page and not self.page.is_closed():
            try:
                await self.page.evaluate("1")
                alive = True
            except PlaywrightError:
                alive = False
        if not alive:
            if self.context:
                try:
                    pages = [p for p in self.context.pages if not p.is_closed()]
                    if pages:
                        self.page = pages[0]
                        return self.page
                    self.page = await self.context.new_page()
                    return self.page
                except PlaywrightError:
                    pass
            logger.warning("Браузер был закрыт — перезапускаю")
            await self.stop()
            await self.start()
        return self.page

    # ---------------------------------------------------------- навигация
    async def goto(self, url: str, settle_ms: tuple[int, int] = (1500, 3000)) -> Page:
        page = await self.ensure_alive()
        retries = int(self.cfg.get("protection.network_retries", 3))
        delay = 3
        for attempt in range(retries + 1):
            try:
                await page.goto(url, wait_until="domcontentloaded")
                break
            except PlaywrightError as e:
                if "net::ERR_ABORTED" in str(e) and await self.detect_block():
                    break
                if attempt >= retries:
                    raise NetworkError(f"{url}: {e}") from e
                logger.warning("Не открылась страница (попытка {}/{}): {}", attempt + 1, retries, str(e)[:200])
                await asyncio.sleep(delay)
                delay *= 3
                page = await self.ensure_alive()
        await page.wait_for_timeout(random.randint(*settle_ms))
        await self.raise_if_blocked()
        return page

    async def detect_block(self, page: Page | None = None) -> str | None:
        page = page or self.page
        if not page or page.is_closed():
            return None
        try:
            return await page.evaluate(_DETECT_JS, {
                "captcha": S.CAPTCHA, "blockWords": S.BLOCK_TITLE_WORDS,
                "loginUrl": S.LOGIN_URL_PARTS, "loginForm": S.LOGIN_FORM,
            })
        except PlaywrightError:
            return None

    async def raise_if_blocked(self, page: Page | None = None) -> None:
        kind = await self.detect_block(page)
        if kind:
            raise AvitoBlocked(kind)

    async def is_logged_in(self) -> bool:
        page = await self.ensure_alive()
        for sel in S.LOGGED_OUT:
            try:
                if await page.locator(sel).count():
                    return False
            except PlaywrightError:
                continue
        return True

    async def first_visible(self, selectors: list[str], timeout_ms: int = 0, page: Page | None = None):
        """Первый видимый элемент из списка селекторов (ждёт до timeout_ms)."""
        page = page or self.page
        waited = 0
        while True:
            for sel in selectors:
                try:
                    loc = page.locator(sel)
                    n = await loc.count()
                    for i in range(min(n, 5)):
                        if await loc.nth(i).is_visible():
                            return loc.nth(i)
                except PlaywrightError:
                    continue
            if waited >= timeout_ms:
                return None
            await page.wait_for_timeout(500)
            waited += 500

    async def screenshot(self, name: str = "screen.png") -> Path | None:
        try:
            path = DATA_DIR / name
            await self.page.screenshot(path=str(path), full_page=False)
            return path
        except Exception as e:
            logger.warning("Не удалось сделать скриншот: {}", e)
            return None
