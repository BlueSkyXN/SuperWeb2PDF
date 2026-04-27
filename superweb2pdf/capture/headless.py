"""Playwright 无头 Chromium 截图后端

启动无头 Chromium 访问 URL，自动滚动触发懒加载，返回全页截图。

前置条件：
    - 安装 playwright: ``pip install playwright``
    - 安装浏览器: ``playwright install chromium``
"""

from __future__ import annotations

import io
import sys

from PIL import Image

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _launch_browser(playwright):
    """Launch headless Chromium, raising a friendly error on failure."""
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        raise RuntimeError(
            "Failed to launch Chromium. Make sure the browser is installed:\n"
            "    playwright install chromium\n"
            f"Original error: {exc}"
        ) from exc


def _auto_scroll(page, scroll_delay_ms: int, verbose: bool) -> None:
    """Scroll the full page in viewport-height chunks to trigger lazy loading.

    After the scroll pass the page is scrolled back to the top.
    """
    delay_ms = max(int(scroll_delay_ms), 0)

    page.evaluate(
        "() => {"
        "  const el = document.scrollingElement || document.documentElement;"
        "  if (el) el.scrollTop = 0;"
        "  window.scrollTo(0, 0);"
        "}"
    )
    page.wait_for_timeout(delay_ms)

    viewport_height = page.evaluate("window.innerHeight") or 800
    scroll_height = page.evaluate("document.documentElement.scrollHeight") or viewport_height
    pos = 0

    while pos < scroll_height:
        pos += viewport_height
        page.evaluate(
            "(y) => {"
            "  const el = document.scrollingElement || document.documentElement;"
            "  if (el) el.scrollTop = y;"
            "  window.scrollTo(0, y);"
            "}",
            pos,
        )
        page.wait_for_timeout(delay_ms)
        # Lazy loading may have increased scroll height
        scroll_height = page.evaluate("document.documentElement.scrollHeight")

    if verbose:
        print(
            f"  Scrolled page (final height: {scroll_height}px)",
            file=sys.stderr,
        )

    page.evaluate(
        "() => {"
        "  const el = document.scrollingElement || document.documentElement;"
        "  if (el) el.scrollTop = 0;"
        "  window.scrollTo(0, 0);"
        "}"
    )
    page.wait_for_timeout(delay_ms)
    page.wait_for_function(
        "() => (window.pageYOffset || document.documentElement.scrollTop || 0) === 0",
        timeout=5_000,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def capture_url(
    url: str,
    scroll_delay_ms: int = 800,
    viewport_width: int = 1280,
    verbose: bool = False,
    *,
    viewport_height: int = 900,
) -> Image.Image:
    """Capture a full-page screenshot of *url* using headless Chromium.

    1. Launches Playwright Chromium in headless mode.
    2. Navigates to the URL and waits for network idle.
    3. Scrolls through the page to trigger lazy-loaded content.
    4. Takes a full-page screenshot and returns it as a PIL Image.

    Args:
        url: The web page URL to capture.
        scroll_delay_ms: Delay between scroll steps (ms) for lazy loading.
        viewport_width: Browser viewport width in CSS pixels.
        viewport_height: Browser viewport height in CSS pixels.
        verbose: Print progress messages to stderr.

    Returns:
        An RGB PIL Image of the full page.

    Raises:
        RuntimeError: If the browser cannot be launched or navigation fails.
    """
    try:
        from playwright.sync_api import TimeoutError as PWTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for headless capture mode. Install it with:\n"
            "    pip install playwright\n"
            "Then install Chromium:\n"
            "    playwright install chromium"
        ) from exc

    def _log(msg: str) -> None:
        if verbose:
            print(msg, file=sys.stderr)

    _log(f"Launching headless Chromium (viewport: {viewport_width}×{viewport_height}px)…")

    with sync_playwright() as pw:
        browser = _launch_browser(pw)
        try:
            context = browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
            )
            page = context.new_page()

            # -- Navigate --------------------------------------------------
            _log(f"Navigating to {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except PWTimeoutError:
                    _log("Network did not become idle; continuing after DOM load")
            except PWTimeoutError:
                raise RuntimeError(f"Timed out waiting for page to load: {url}")
            except Exception as exc:
                raise RuntimeError(f"Failed to navigate to {url}: {exc}") from exc

            _log(f"Page loaded: {page.title()}")

            # -- Lazy-loading scroll pass ----------------------------------
            _log("Scrolling page to trigger lazy loading…")
            _auto_scroll(page, scroll_delay_ms, verbose)

            # -- Screenshot ------------------------------------------------
            _log("Taking full-page screenshot…")
            screenshot_bytes = page.screenshot(full_page=True)

            img = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
            _log(f"Screenshot captured: {img.width}×{img.height}")
            return img
        finally:
            browser.close()
