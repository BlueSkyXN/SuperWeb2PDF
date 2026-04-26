# -*- coding: utf-8 -*-
"""CDP (Chrome DevTools Protocol) 截图后端

连接已运行的 Chrome 实例，通过 CDP 协议截取全页截图。
Chrome 需以 ``--remote-debugging-port`` 参数启动::

    google-chrome --remote-debugging-port=9222

用法::

    from superweb2pdf.capture.cdp import capture_via_cdp
    img = capture_via_cdp("https://example.com", cdp_port=9222)
"""

from __future__ import annotations

import io
import sys
import urllib.error
import urllib.request

from PIL import Image


# ---------------------------------------------------------------------------
# CDP availability check
# ---------------------------------------------------------------------------

def check_cdp_available(port: int = 9222, timeout: float = 0.5) -> bool:
    """Return *True* if a CDP endpoint is reachable on *port*.

    Performs a quick HTTP GET to ``http://localhost:{port}/json/version``.
    """
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/json/version",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _auto_scroll(page, scroll_delay_ms: int, verbose: bool) -> None:
    """Scroll through the full page to trigger lazy-loaded content."""
    delay_ms = max(scroll_delay_ms, 100)

    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(delay_ms)

    viewport_height = page.evaluate("document.documentElement.clientHeight") or 800
    scroll_height = page.evaluate("document.documentElement.scrollHeight") or viewport_height
    pos = 0

    while pos < scroll_height:
        pos += viewport_height
        page.evaluate(f"window.scrollTo(0, {pos})")
        page.wait_for_timeout(delay_ms)
        # Lazy loading may increase scroll height
        scroll_height = page.evaluate("document.documentElement.scrollHeight")

    # Scroll back to top before the screenshot
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(delay_ms)

    if verbose:
        final_height = page.evaluate("document.documentElement.scrollHeight")
        print(f"  Scrolled page (height: {final_height}px)", file=sys.stderr)


def _all_pages(browser) -> list:
    """Return all open CDP pages across all browser contexts."""
    pages = []
    for context in browser.contexts:
        pages.extend(context.pages)
    return pages


def _select_page(browser):
    """Pick the most likely active tab from a CDP-connected Chrome browser.

    CDP does not expose "frontmost tab" directly through Playwright. In
    practice, the active tab reports ``document.visibilityState === "visible"``
    while background tabs are usually ``hidden``. Fall back to the most recently
    enumerated page rather than always taking contexts[0].pages[0].
    """
    pages = _all_pages(browser)
    if not pages:
        raise RuntimeError(
            "Connected to Chrome but found no open pages. Please open at least one tab."
        )

    for page in reversed(pages):
        try:
            if page.evaluate("document.visibilityState") == "visible":
                return page
        except Exception:
            continue
    return pages[-1]


# ---------------------------------------------------------------------------
# Main capture function
# ---------------------------------------------------------------------------

def capture_via_cdp(
    url: str | None,
    cdp_port: int = 9222,
    scroll_delay_ms: int = 800,
    viewport_width: int | None = None,
    verbose: bool = False,
) -> Image.Image:
    """Capture a full-page screenshot via Chrome DevTools Protocol.

    Connects to a running Chrome instance, optionally navigates to *url*,
    scrolls the page to trigger lazy loading, and returns a full-page
    screenshot as a PIL Image.

    Args:
        url: URL to navigate to.  If ``None``, captures the current active
            page without navigation.
        cdp_port: Chrome remote-debugging port (default 9222).
        scroll_delay_ms: Delay between scroll steps in ms for lazy loading.
        viewport_width: If set, resize the viewport width before capture.
        verbose: Print progress messages to stderr.

    Returns:
        A PIL Image of the full page.

    Raises:
        RuntimeError: If Chrome is not reachable on the given port or if
            the browser has no open pages.
    """
    try:
        from playwright.sync_api import TimeoutError as PWTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for CDP capture mode. Install it with:\n"
            "    pip install playwright\n"
            "Then install a browser if needed:\n"
            "    playwright install chromium"
        ) from exc

    def _log(msg: str) -> None:
        if verbose:
            print(msg, file=sys.stderr)

    endpoint = f"http://localhost:{cdp_port}"

    with sync_playwright() as pw:
        # -- Connect to Chrome -------------------------------------------------
        try:
            browser = pw.chromium.connect_over_cdp(endpoint)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot connect to Chrome on port {cdp_port}.\n"
                "Make sure Chrome is running with remote debugging enabled:\n"
                f"  google-chrome --remote-debugging-port={cdp_port}\n"
                "or on macOS:\n"
                "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
                f"--remote-debugging-port={cdp_port}"
            ) from exc

        _log(f"Connected to Chrome on port {cdp_port}")

        try:
            # -- Get the active page -------------------------------------------
            page = _select_page(browser)

            # -- Optionally resize viewport ------------------------------------
            if viewport_width is not None:
                current_height = page.evaluate("window.innerHeight") or 900
                page.set_viewport_size(
                    {"width": viewport_width, "height": current_height}
                )
                _log(f"Viewport width set to {viewport_width}px")

            # -- Navigate if URL provided --------------------------------------
            if url is not None:
                _log(f"Navigating to {url} …")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except PWTimeoutError:
                        _log("Network did not become idle; continuing after DOM load")
                except PWTimeoutError as exc:
                    raise RuntimeError(f"Timed out navigating to {url}") from exc
                _log("Page loaded")
            else:
                _log(f"Capturing current page: {page.url}")
                # Wait briefly for any in-flight requests to settle
                try:
                    page.wait_for_load_state("networkidle", timeout=5_000)
                except PWTimeoutError:
                    _log("Network did not become idle; continuing with current page")

            # -- Auto-scroll for lazy loading ----------------------------------
            _log("Scrolling for lazy-loaded content…")
            _auto_scroll(page, scroll_delay_ms, verbose)

            # -- Full-page screenshot ------------------------------------------
            _log("Taking full-page screenshot…")
            screenshot_bytes = page.screenshot(full_page=True)

            image = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
            _log(f"Screenshot captured: {image.width}×{image.height}")

            return image

        finally:
            # For a browser obtained via connect_over_cdp(), Playwright closes
            # the client-side CDP connection/context wrapper; it does not launch
            # or own the user's Chrome process.
            browser.close()
