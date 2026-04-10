# -*- coding: utf-8 -*-
"""AppleScript + Quartz 截图后端（macOS Chrome）

通过 AppleScript 控制 Chrome 滚动 + Quartz CGWindowListCreateImage 逐屏截图，
自动裁剪工具栏并拼接为完整长图。

前置条件：
    - macOS + Google Chrome
    - Chrome → 视图 → 开发者 → 勾选「允许 Apple 事件中的 JavaScript」
    - 终端/IDE 需有屏幕录制权限
"""

from __future__ import annotations

import subprocess
import sys
import time

import Quartz
from PIL import Image


# ---------------------------------------------------------------------------
# AppleScript helpers
# ---------------------------------------------------------------------------

def run_applescript(script: str) -> str:
    """Execute an AppleScript snippet and return its stdout result.

    Raises:
        RuntimeError: If ``osascript`` exits with a non-zero status.
    """
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"AppleScript failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def get_chrome_tab_info() -> dict:
    """Return the active Chrome tab's URL, title, and internal window ID."""
    script = (
        'tell application "Google Chrome" to get '
        "{URL of active tab of window 1, title of active tab of window 1, id of window 1}"
    )
    raw = run_applescript(script)
    # osascript returns comma-separated values.  The window ID is always the
    # last token (a plain integer), so parse from the right to handle titles
    # that contain commas, e.g. "https://…, Hello, World, 12345".
    rparts = raw.rsplit(", ", 1)
    if len(rparts) < 2:
        raise RuntimeError(f"Unexpected AppleScript output: {raw}")
    window_id = int(rparts[1])
    # Now split the remainder (URL + title) — URL never contains ", "
    left = rparts[0]
    lparts = left.split(", ", 1)
    if len(lparts) < 2:
        raise RuntimeError(f"Unexpected AppleScript output: {raw}")
    return {
        "url": lparts[0],
        "title": lparts[1],
        "window_id": window_id,
    }


def execute_js_in_chrome(js_code: str) -> str:
    """Execute JavaScript in Chrome's active tab via AppleScript.

    Raises:
        RuntimeError: With a human-friendly message when JS execution is
            blocked (the "Allow JavaScript from Apple Events" setting).
    """
    escaped = js_code.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        'tell application "Google Chrome" to tell active tab of window 1 '
        f'to execute javascript "{escaped}"'
    )
    try:
        return run_applescript(script)
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "not allowed" in msg or "javascript" in msg:
            raise RuntimeError(
                "Chrome blocked JavaScript execution from AppleScript.\n"
                "Enable it via: Chrome → View → Developer → "
                '"Allow JavaScript from Apple Events"'
            ) from exc
        raise


# ---------------------------------------------------------------------------
# Page inspection / scrolling
# ---------------------------------------------------------------------------

def get_page_dimensions() -> dict:
    """Return page geometry from the active Chrome tab.

    Keys: scrollHeight, scrollWidth, clientHeight, clientWidth, devicePixelRatio
    """
    js = (
        "JSON.stringify({"
        "scrollHeight: document.documentElement.scrollHeight,"
        "scrollWidth: document.documentElement.scrollWidth,"
        "clientHeight: document.documentElement.clientHeight,"
        "clientWidth: document.documentElement.clientWidth,"
        "devicePixelRatio: window.devicePixelRatio"
        "})"
    )
    import json

    raw = execute_js_in_chrome(js)
    return json.loads(raw)


def scroll_page(y_position: int) -> None:
    """Scroll Chrome's active tab to the given vertical offset (CSS px)."""
    execute_js_in_chrome(f"window.scrollTo(0, {y_position})")


def auto_scroll_for_lazy_loading(scroll_delay_ms: int = 800) -> None:
    """Scroll the full page once to trigger lazy-loaded content.

    After the scroll pass the page is scrolled back to the top.
    """
    delay_s = scroll_delay_ms / 1000.0

    scroll_page(0)
    time.sleep(delay_s)

    dims = get_page_dimensions()
    viewport_h = dims["clientHeight"]
    scroll_h = dims["scrollHeight"]
    pos = 0

    while pos < scroll_h:
        pos += viewport_h
        scroll_page(pos)
        time.sleep(delay_s)
        # Re-check: lazy loading may have increased scroll height
        scroll_h = get_page_dimensions()["scrollHeight"]

    scroll_page(0)
    time.sleep(delay_s)


# ---------------------------------------------------------------------------
# Quartz window capture
# ---------------------------------------------------------------------------

def _cgimage_to_pil(cgimage) -> Image.Image:
    """Convert a Quartz CGImage to a PIL RGB Image."""
    width = Quartz.CGImageGetWidth(cgimage)
    height = Quartz.CGImageGetHeight(cgimage)
    bytes_per_row = Quartz.CGImageGetBytesPerRow(cgimage)

    pixel_data = Quartz.CGDataProviderCopyData(
        Quartz.CGImageGetDataProvider(cgimage)
    )
    img = Image.frombytes(
        "RGBA", (width, height), pixel_data, "raw", "BGRA", bytes_per_row, 1
    )
    return img.convert("RGB")


def _get_chrome_window_number() -> int:
    """Return the macOS CGWindowID for Chrome's frontmost regular window.

    This is *not* the same as Chrome's internal ``id of window 1``.

    Raises:
        RuntimeError: If no on-screen Chrome window is found.
    """
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    for w in windows:
        if w.get("kCGWindowOwnerName") == "Google Chrome":
            if w.get("kCGWindowLayer", 0) == 0:
                return w["kCGWindowNumber"]
    raise RuntimeError(
        "No Chrome window found on screen. Is Chrome running and not minimised?"
    )


def capture_chrome_window() -> Image.Image:
    """Capture Chrome's frontmost window via Quartz and return a PIL Image."""
    wid = _get_chrome_window_number()
    cgimage = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        wid,
        Quartz.kCGWindowImageBoundsIgnoreFraming
        | Quartz.kCGWindowImageBestResolution,
    )
    if cgimage is None:
        raise RuntimeError(
            "Quartz failed to capture the Chrome window. "
            "Check that screen-recording permission is granted."
        )
    return _cgimage_to_pil(cgimage)


# ---------------------------------------------------------------------------
# Content-area cropping
# ---------------------------------------------------------------------------

def calculate_content_crop(
    window_image: Image.Image,
    viewport_height: int,
    viewport_width: int,
    device_pixel_ratio: float,
) -> tuple[int, int, int, int]:
    """Return ``(left, top, right, bottom)`` to crop the page content area.

    Chrome's title/tab/address/bookmarks bars sit above the viewport.  We
    derive the toolbar height from the difference between the full capture
    size and the known viewport dimensions (scaled by *device_pixel_ratio*).
    """
    img_w, img_h = window_image.size
    content_w = int(viewport_width * device_pixel_ratio)
    content_h = int(viewport_height * device_pixel_ratio)

    top = img_h - content_h
    left = (img_w - content_w) // 2
    right = left + content_w
    bottom = img_h

    # Clamp to image bounds
    left = max(0, left)
    top = max(0, top)
    right = min(img_w, right)
    bottom = min(img_h, bottom)

    return (left, top, right, bottom)


# ---------------------------------------------------------------------------
# Full-page capture orchestration
# ---------------------------------------------------------------------------

def capture_current_tab(
    scroll_delay_ms: int = 800,
    verbose: bool = False,
) -> Image.Image:
    """Capture the entire page of Chrome's current tab.

    1. Reads tab info and page dimensions.
    2. Scrolls through the page to trigger lazy loading.
    3. For each viewport-height section, scrolls, waits, captures via Quartz,
       and crops to the content area.
    4. Stitches all sections into one tall image.

    Args:
        scroll_delay_ms: Delay between scroll steps (ms) for lazy loading.
        verbose: Print progress to stderr.

    Returns:
        A PIL Image of the full page content.
    """
    def _log(msg: str) -> None:
        if verbose:
            print(msg, file=sys.stderr)

    # -- 1. Tab info --------------------------------------------------------
    tab = get_chrome_tab_info()
    _log(f"Tab: {tab['title']}  ({tab['url'][:80]})")

    # -- 2. Page dimensions -------------------------------------------------
    dims = get_page_dimensions()
    viewport_h = dims["clientHeight"]
    viewport_w = dims["clientWidth"]
    dpr = dims["devicePixelRatio"]
    scroll_h = dims["scrollHeight"]
    _log(
        f"Viewport: {viewport_w}×{viewport_h}  "
        f"Page height: {scroll_h}  DPR: {dpr}"
    )

    # -- 3. Lazy-loading pre-scroll -----------------------------------------
    _log("Pre-scrolling for lazy loading…")
    auto_scroll_for_lazy_loading(scroll_delay_ms)

    # Re-read dimensions; scroll height may have changed
    dims = get_page_dimensions()
    scroll_h = dims["scrollHeight"]
    _log(f"Page height after lazy-load scroll: {scroll_h}")

    # -- 4. Capture each viewport section -----------------------------------
    sections: list[Image.Image] = []
    y = 0
    step = 0

    while y < scroll_h:
        step += 1
        scroll_page(y)
        time.sleep(0.2)  # let Chrome render

        win_img = capture_chrome_window()
        crop_box = calculate_content_crop(win_img, viewport_h, viewport_w, dpr)
        section = win_img.crop(crop_box)
        sections.append(section)

        remaining_css = scroll_h - y
        if remaining_css < viewport_h:
            # Last section may be shorter; crop the overlap
            actual_content_h = int(remaining_css * dpr)
            if actual_content_h < section.height:
                # Keep only the bottom slice that contains new content
                section_top = section.height - actual_content_h
                sections[-1] = section.crop(
                    (0, section_top, section.width, section.height)
                )

        _log(f"  Section {step}: scroll_y={y}")
        y += viewport_h

    if not sections:
        raise RuntimeError("No sections captured – page may be empty.")

    # -- 5. Stitch ----------------------------------------------------------
    total_w = sections[0].width
    total_h = sum(s.height for s in sections)
    stitched = Image.new("RGB", (total_w, total_h))
    offset_y = 0
    for s in sections:
        stitched.paste(s, (0, offset_y))
        offset_y += s.height

    _log(f"Final image: {stitched.width}×{stitched.height}")
    return stitched
