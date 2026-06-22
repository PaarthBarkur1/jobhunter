"""Asynchronous browser manager to reuse Playwright and control concurrency.

Provides `get_page()` async context manager which yields a ready `page`. The
manager launches Playwright once and keeps a single persistent browser context
to avoid repeated cold starts. A semaphore limits the number of concurrent
pages to avoid overwhelming resources.
"""
from contextlib import asynccontextmanager
import asyncio
import logging
from typing import AsyncIterator, Optional

from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page

logger = logging.getLogger("browser_manager")

# Tunable concurrency limit
DEFAULT_MAX_CONCURRENT_PAGES = 3

_playwright: Optional[Playwright] = None
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None
_semaphore: Optional[asyncio.Semaphore] = None
# Protect startup so multiple coroutines don't race to start Playwright
_start_lock: Optional[asyncio.Lock] = None


async def _ensure_started(user_data_dir: Optional[str] = None, headless: bool = True, max_concurrent: int = DEFAULT_MAX_CONCURRENT_PAGES):
    global _playwright, _browser, _context, _semaphore, _start_lock
    if _start_lock is None:
        _start_lock = asyncio.Lock()

    async with _start_lock:
        if _playwright is not None and _context is not None:
            return

        # Try a few times to start Playwright and create a browser context
        attempts = 3
        backoff = 0.5
        for attempt in range(1, attempts + 1):
            try:
                if _playwright is None:
                    _playwright = await async_playwright().start()

                # Prefer a persistent context if user_data_dir is provided
                if user_data_dir:
                    try:
                        _browser = await _playwright.chromium.launch_persistent_context(user_data_dir=user_data_dir, headless=headless, viewport={"width": 1280, "height": 800})
                        # When using persistent context, _browser acts as a context
                        _context = _browser  # type: ignore
                    except Exception:
                        # Fallback to a regular browser + new_context
                        _browser = await _playwright.chromium.launch(headless=headless)
                        _context = await _browser.new_context(viewport={"width": 1280, "height": 800})
                else:
                    _browser = await _playwright.chromium.launch(headless=headless)
                    _context = await _browser.new_context(viewport={"width": 1280, "height": 800})

                _semaphore = asyncio.Semaphore(max_concurrent)
                logger.info("Playwright started and browser context initialized")
                return
            except Exception as e:
                logger.warning(f"Playwright start attempt {attempt} failed: {e}")
                # Clean up partially initialized objects
                try:
                    if _browser:
                        await _browser.close()
                except Exception:
                    pass
                _browser = None
                _context = None
                _playwright = None
                if attempt < attempts:
                    await asyncio.sleep(backoff * attempt)

        raise RuntimeError("Failed to start Playwright after multiple attempts")


@asynccontextmanager
async def get_page(user_data_dir: Optional[str] = None, headless: bool = True, max_concurrent: int = DEFAULT_MAX_CONCURRENT_PAGES) -> AsyncIterator[Page]:
    """Yield an isolated `Page` from the shared browser context.

    Acquires a semaphore slot to limit concurrency. The `user_data_dir` and
    `headless` args are accepted for compatibility with older helpers but are
    applied only on the first start.
    """
    await _ensure_started(user_data_dir=user_data_dir, headless=headless, max_concurrent=max_concurrent)
    if _context is None or _semaphore is None:
        raise RuntimeError("Browser context not initialized")

    await _semaphore.acquire()

    # Safely create a page; if the context is invalid, attempt to restart once
    page = None
    try:
        try:
            page = await _context.new_page()
        except Exception as e:
            logger.warning(f"Failed to create new page from context: {e}. Restarting context and retrying...")
            # Try to restart browser/context once
            try:
                await close()
            except Exception:
                pass
            await _ensure_started(user_data_dir=user_data_dir, headless=headless, max_concurrent=max_concurrent)
            if _context is None:
                raise
            page = await _context.new_page()

        try:
            yield page
        finally:
            try:
                if page:
                    await page.close()
            except Exception:
                pass
    finally:
        _semaphore.release()


async def close() -> None:
    """Close the browser and stop Playwright."""
    global _playwright, _browser, _context, _semaphore
    try:
        if _context:
            await _context.close()
        if _browser:
            await _browser.close()
        if _playwright:
            await _playwright.stop()
    finally:
        _playwright = None
        _browser = None
        _context = None
        _semaphore = None
