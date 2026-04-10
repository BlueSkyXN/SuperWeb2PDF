# -*- coding: utf-8 -*-
"""PDF 生成模块

将页面图片列表转为分页 PDF（reportlab）。
支持固定纸张尺寸（A4、Letter 等）和自适应尺寸模式。
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Standard paper sizes in millimetres (width, height).
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "a4": (210, 297),
    "a3": (297, 420),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
}

#: 1 mm expressed in PDF points (1/72 inch).
_MM_TO_PT: float = 2.834645669


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def mm_to_points(mm: float) -> float:
    """Convert millimetres to PDF points."""
    return mm * _MM_TO_PT


def px_to_mm(px: int, dpi: int) -> float:
    """Convert pixels to millimetres at the given DPI."""
    return px / dpi * 25.4


# ---------------------------------------------------------------------------
# Paper-size parser
# ---------------------------------------------------------------------------

_CUSTOM_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)$")


def parse_paper_size(spec: str) -> tuple[float, float]:
    """Parse a paper-size specification string.

    Accepts named sizes (case-insensitive) such as ``"a4"`` or ``"letter"``,
    and custom ``"WxH"`` specifications in millimetres (e.g. ``"200x300"``).

    Parameters
    ----------
    spec:
        Paper-size specification string.

    Returns
    -------
    tuple[float, float]
        ``(width_mm, height_mm)``

    Raises
    ------
    ValueError
        If *spec* cannot be parsed or references an unknown named size.
    """
    spec = spec.strip()
    key = spec.lower()

    if key in PAPER_SIZES:
        return PAPER_SIZES[key]

    m = _CUSTOM_RE.match(spec)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        if w <= 0 or h <= 0:
            raise ValueError(f"Paper dimensions must be positive, got {w}x{h}")
        return (w, h)

    raise ValueError(
        f"Unknown paper size {spec!r}. "
        f"Use a named size ({', '.join(sorted(PAPER_SIZES))}) "
        f"or WxH in mm (e.g. '200x300')."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pil_to_reader(img: Image.Image) -> ImageReader:
    """Wrap a PIL image in a reportlab ``ImageReader``."""
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _fit_image_on_page(
    img_w_px: int,
    img_h_px: int,
    page_w_pt: float,
    page_h_pt: float,
) -> tuple[float, float, float, float]:
    """Compute draw position and size for an image centred on a page.

    The image is scaled to fit entirely within the page while keeping its
    aspect ratio.  Returns ``(x, y, draw_w, draw_h)`` in points.
    """
    if img_w_px <= 0 or img_h_px <= 0:
        raise ValueError(f"Invalid image dimensions: {img_w_px}×{img_h_px}")
    img_aspect = img_w_px / img_h_px
    page_aspect = page_w_pt / page_h_pt

    if img_aspect > page_aspect:
        # image is wider relative to page → constrain by width
        draw_w = page_w_pt
        draw_h = page_w_pt / img_aspect
    else:
        # image is taller relative to page → constrain by height
        draw_h = page_h_pt
        draw_w = page_h_pt * img_aspect

    x = (page_w_pt - draw_w) / 2
    y = (page_h_pt - draw_h) / 2
    return x, y, draw_w, draw_h


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_pdf(
    page_images: list[Image.Image],
    output_path: str | Path,
    paper_size: tuple[float, float] = (210, 297),
    dpi: int = 150,
) -> Path:
    """Build a PDF with fixed paper size from a list of page images.

    Each image is scaled to fit the paper while maintaining aspect ratio and
    centred on the page.

    Parameters
    ----------
    page_images:
        PIL images, one per PDF page.
    output_path:
        Destination file path.
    paper_size:
        ``(width_mm, height_mm)`` of every page.  Defaults to A4.
    dpi:
        Nominal DPI used for the PDF metadata (does not resample images).

    Returns
    -------
    Path
        The resolved *output_path*.

    Raises
    ------
    ValueError
        If *page_images* is empty.
    """
    if not page_images:
        raise ValueError("page_images must not be empty")

    output_path = Path(output_path)
    page_w_pt = mm_to_points(paper_size[0])
    page_h_pt = mm_to_points(paper_size[1])

    c = canvas.Canvas(str(output_path), pagesize=(page_w_pt, page_h_pt))

    for img in page_images:
        reader = _pil_to_reader(img)
        x, y, draw_w, draw_h = _fit_image_on_page(
            img.width, img.height, page_w_pt, page_h_pt
        )
        c.drawImage(reader, x, y, width=draw_w, height=draw_h)
        c.showPage()

    c.save()
    return output_path


def build_pdf_auto_size(
    page_images: list[Image.Image],
    output_path: str | Path,
    dpi: int = 150,
) -> Path:
    """Build a PDF where each page matches its image dimensions exactly.

    No fixed paper size is used — every page is sized so that the image fills
    it completely at the given *dpi*.

    Parameters
    ----------
    page_images:
        PIL images, one per PDF page.
    output_path:
        Destination file path.
    dpi:
        Resolution used to convert pixel dimensions to physical size.

    Returns
    -------
    Path
        The resolved *output_path*.

    Raises
    ------
    ValueError
        If *page_images* is empty.
    """
    if not page_images:
        raise ValueError("page_images must not be empty")

    output_path = Path(output_path)

    # Use the first image to initialise the canvas; each page will override.
    first = page_images[0]
    init_w = mm_to_points(px_to_mm(first.width, dpi))
    init_h = mm_to_points(px_to_mm(first.height, dpi))
    c = canvas.Canvas(str(output_path), pagesize=(init_w, init_h))

    for img in page_images:
        page_w_pt = mm_to_points(px_to_mm(img.width, dpi))
        page_h_pt = mm_to_points(px_to_mm(img.height, dpi))
        c.setPageSize((page_w_pt, page_h_pt))

        reader = _pil_to_reader(img)
        c.drawImage(reader, 0, 0, width=page_w_pt, height=page_h_pt)
        c.showPage()

    c.save()
    return output_path
