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

import json
import platform
import subprocess
import sys
import time
from typing import Any

from PIL import Image

if sys.platform == "darwin":
    try:
        import Quartz as _Quartz
    except ImportError:  # pragma: no cover - depends on macOS/PyObjC install
        _Quartz = None
else:  # Keep this module importable on Linux/Windows.
    _Quartz = None


def _quartz() -> Any:
    """Return the Quartz module, or raise a platform-specific friendly error."""
    if sys.platform != "darwin":
        raise RuntimeError(
            "The AppleScript/Quartz capture backend is only available on macOS "
            f"(current platform: {platform.system() or sys.platform})."
        )
    if _Quartz is None:
        raise RuntimeError(
            "Quartz/PyObjC is required for macOS window capture. "
            "Install the macOS dependencies for this package, e.g. pyobjc-framework-Quartz."
        )
    return _Quartz


def _require_macos() -> None:
    """Raise a friendly error when AppleScript capture is used off macOS."""
    if sys.platform != "darwin":
        raise RuntimeError(
            "The AppleScript capture backend is only available on macOS "
            f"(current platform: {platform.system() or sys.platform})."
        )


# ---------------------------------------------------------------------------
# AppleScript helpers
# ---------------------------------------------------------------------------

def run_applescript(script: str, args: list[str] | None = None) -> str:
    """Execute an AppleScript snippet and return its stdout result.

    Raises:
        RuntimeError: If ``osascript`` exits with a non-zero status.
    """
    _require_macos()
    result = subprocess.run(
        ["osascript", "-e", script, *(args or [])],
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
    # Use an ASCII unit separator instead of AppleScript's default
    # comma-separated list formatting. Titles and URLs may contain ", " or
    # terminal-looking integer tokens, which makes comma-based parsing
    # ambiguous.
    sep = "\x1f"
    script = """
tell application "Google Chrome"
    set _tab to active tab of window 1
    set _sep to ASCII character 31
    return (URL of _tab) & _sep & (title of _tab) & _sep & ((id of window 1) as text)
end tell
"""
    raw = run_applescript(script)
    parts = raw.split(sep)
    if len(parts) != 3:
        raise RuntimeError(f"Unexpected AppleScript output: {raw}")
    url, title, window_id_raw = parts
    try:
        window_id = int(window_id_raw)
    except ValueError as exc:
        raise RuntimeError(f"Unexpected Chrome window id: {window_id_raw!r}") from exc
    return {
        "url": url,
        "title": title,
        "window_id": window_id,
    }


def execute_js_in_chrome(js_code: str) -> str:
    """Execute JavaScript in Chrome's active tab via AppleScript.

    Raises:
        RuntimeError: With a human-friendly message when JS execution is
            blocked (the "Allow JavaScript from Apple Events" setting).
    """
    # Pass JavaScript as an osascript argv item instead of interpolating it
    # into AppleScript source. This safely handles quotes, backslashes,
    # newlines, Unicode, and other special characters.
    script = """
on run argv
    tell application "Google Chrome" to tell active tab of window 1
        execute javascript (item 1 of argv)
    end tell
end run
"""
    try:
        return run_applescript(script, [js_code])
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
    raw = execute_js_in_chrome(js)
    return json.loads(raw)


def scroll_page(y_position: int) -> None:
    """Scroll Chrome's active tab to the given vertical offset (CSS px)."""
    execute_js_in_chrome(f"window.scrollTo(0, {max(0, int(y_position))})")


def get_scroll_y() -> int:
    """Return the active tab's current vertical scroll offset in CSS px."""
    raw = execute_js_in_chrome(
        "String(window.pageYOffset || document.documentElement.scrollTop || "
        "document.body.scrollTop || 0)"
    )
    try:
        return int(float(raw or 0))
    except ValueError:
        return 0


def _prepare_page_for_capture() -> None:
    """Loosen root overflow styles when they prevent normal page scrolling."""
    js = r"""
(function () {
  const root = document.documentElement;
  const body = document.body;
  window.__superweb2pdfOriginalOverflow = window.__superweb2pdfOriginalOverflow || {
    rootOverflow: root ? root.style.overflow : "",
    rootOverflowY: root ? root.style.overflowY : "",
    bodyOverflow: body ? body.style.overflow : "",
    bodyOverflowY: body ? body.style.overflowY : ""
  };

  if (document.documentElement.scrollHeight > document.documentElement.clientHeight) {
    window.scrollTo(0, 1);
    const canScroll = (window.pageYOffset || document.documentElement.scrollTop || 0) > 0;
    window.scrollTo(0, 0);
    if (!canScroll) {
      if (root) {
        root.style.overflow = "auto";
        root.style.overflowY = "auto";
      }
      if (body) {
        body.style.overflow = "auto";
        body.style.overflowY = "auto";
      }
    }
  }
})();
"""
    execute_js_in_chrome(js)


def _restore_page_after_capture() -> None:
    """Restore overflow styles modified by :func:`_prepare_page_for_capture`."""
    js = r"""
(function () {
  const saved = window.__superweb2pdfOriginalOverflow;
  if (!saved) return;
  const root = document.documentElement;
  const body = document.body;
  if (root) {
    root.style.overflow = saved.rootOverflow;
    root.style.overflowY = saved.rootOverflowY;
  }
  if (body) {
    body.style.overflow = saved.bodyOverflow;
    body.style.overflowY = saved.bodyOverflowY;
  }
  delete window.__superweb2pdfOriginalOverflow;
})();
"""
    execute_js_in_chrome(js)


def auto_scroll_for_lazy_loading(scroll_delay_ms: int = 800) -> None:
    """Scroll the full page once to trigger lazy-loaded content.

    After the scroll pass the page is scrolled back to the top.
    """
    delay_s = scroll_delay_ms / 1000.0

    scroll_page(0)
    time.sleep(delay_s)

    dims = get_page_dimensions()
    viewport_h = max(1, int(dims["clientHeight"] or 1))
    scroll_h = max(viewport_h, int(dims["scrollHeight"] or viewport_h))
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
    Quartz = _quartz()
    width = Quartz.CGImageGetWidth(cgimage)
    height = Quartz.CGImageGetHeight(cgimage)
    bytes_per_row = Quartz.CGImageGetBytesPerRow(cgimage)
    bits_per_pixel = Quartz.CGImageGetBitsPerPixel(cgimage)

    if bits_per_pixel != 32:
        raise RuntimeError(
            f"Unsupported Quartz pixel depth: {bits_per_pixel} bits per pixel"
        )

    pixel_data = Quartz.CGDataProviderCopyData(
        Quartz.CGImageGetDataProvider(cgimage)
    )
    bitmap_info = Quartz.CGImageGetBitmapInfo(cgimage)
    byte_order = bitmap_info & Quartz.kCGBitmapByteOrderMask
    alpha_info = bitmap_info & Quartz.kCGBitmapAlphaInfoMask

    first_alpha = {
        Quartz.kCGImageAlphaPremultipliedFirst,
        Quartz.kCGImageAlphaFirst,
        Quartz.kCGImageAlphaNoneSkipFirst,
    }
    last_alpha = {
        Quartz.kCGImageAlphaPremultipliedLast,
        Quartz.kCGImageAlphaLast,
        Quartz.kCGImageAlphaNoneSkipLast,
    }

    if byte_order == Quartz.kCGBitmapByteOrder32Little and alpha_info in first_alpha:
        raw_mode = "BGRA"
    elif byte_order == Quartz.kCGBitmapByteOrder32Little and alpha_info in last_alpha:
        raw_mode = "RGBA"
    elif byte_order == Quartz.kCGBitmapByteOrder32Big and alpha_info in first_alpha:
        raw_mode = "ARGB"
    elif byte_order == Quartz.kCGBitmapByteOrder32Big and alpha_info in last_alpha:
        raw_mode = "RGBA"
    else:
        raise RuntimeError(
            "Unsupported Quartz bitmap layout "
            f"(byte_order={byte_order}, alpha_info={alpha_info})"
        )

    img = Image.frombytes(
        "RGBA", (width, height), pixel_data, "raw", raw_mode, bytes_per_row, 1
    )
    return img.convert("RGB")


def _get_chrome_window_number() -> int:
    """Return the macOS CGWindowID for Chrome's frontmost regular window.

    This is *not* the same as Chrome's internal ``id of window 1``.

    Raises:
        RuntimeError: If no on-screen Chrome window is found.
    """
    Quartz = _quartz()
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
    Quartz = _quartz()
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
    dpr = float(device_pixel_ratio or 1)
    content_w = int(round(viewport_width * dpr))
    content_h = int(round(viewport_height * dpr))

    # If Chrome moved between displays, or Quartz reports a different backing
    # scale than window.devicePixelRatio, the DPR-derived content box can be
    # larger than the captured window. Recalculate a conservative scale that
    # fits in the captured image instead of producing a bogus crop.
    if content_w > img_w or content_h > img_h:
        scale_candidates = []
        if viewport_width > 0:
            scale_candidates.append(img_w / viewport_width)
        if viewport_height > 0:
            scale_candidates.append(img_h / viewport_height)
        effective_scale = min(scale_candidates) if scale_candidates else 1.0
        content_w = int(round(viewport_width * effective_scale))
        content_h = int(round(viewport_height * effective_scale))

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

    try:
        _prepare_page_for_capture()

        # -- 3. Lazy-loading pre-scroll -------------------------------------
        _log("Pre-scrolling for lazy loading…")
        auto_scroll_for_lazy_loading(scroll_delay_ms)

        # Re-read dimensions; scroll height may have changed
        dims = get_page_dimensions()
        viewport_h = dims["clientHeight"]
        viewport_w = dims["clientWidth"]
        dpr = dims["devicePixelRatio"]
        scroll_h = dims["scrollHeight"]
        _log(f"Page height after lazy-load scroll: {scroll_h}")

        # -- 4. Capture each viewport section -------------------------------
        sections: list[Image.Image] = []
        y = 0
        step = 0
        last_actual_y: int | None = None

        while y < max(scroll_h, viewport_h):
            step += 1
            scroll_page(y)
            time.sleep(0.2)  # let Chrome render
            actual_y = get_scroll_y()

            if (
                last_actual_y is not None
                and actual_y <= last_actual_y
                and scroll_h > viewport_h
            ):
                raise RuntimeError(
                    "The page reports more content than one viewport but does "
                    "not scroll. It may use a custom scroll container or locked "
                    "overflow that the AppleScript backend cannot capture reliably."
                )
            last_actual_y = actual_y

            win_img = capture_chrome_window()
            crop_box = calculate_content_crop(win_img, viewport_h, viewport_w, dpr)
            section = win_img.crop(crop_box)

            remaining_css = max(0, scroll_h - actual_y)
            if remaining_css == 0:
                break
            if remaining_css < viewport_h:
                # Last section may be shorter; crop the overlap. Keep only the
                # bottom slice that contains new content, and guard against
                # zero/negative heights caused by scroll snapping or stale dims.
                scale = section.height / max(viewport_h, 1)
                actual_content_h = max(
                    1,
                    min(section.height, int(round(remaining_css * scale))),
                )
                section_top = max(0, section.height - actual_content_h)
                section = section.crop((0, section_top, section.width, section.height))

            sections.append(section)

            _log(f"  Section {step}: requested_y={y}, actual_y={actual_y}")
            y = actual_y + viewport_h
    finally:
        try:
            _restore_page_after_capture()
        except Exception:
            pass

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
