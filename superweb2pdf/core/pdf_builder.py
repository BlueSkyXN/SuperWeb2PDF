"""PDF 生成模块

将页面图片列表转为分页 PDF（reportlab）。
支持固定纸张尺寸（A4、Letter 等）和自适应尺寸模式。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sized
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from itertools import chain
from pathlib import Path
from typing import BinaryIO, Literal

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Standard paper sizes in millimetres (width, height).
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "a4": (210, 297),
    "a3": (297, 420),
    "b5": (176, 250),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
    "tabloid": (279.4, 431.8),
}

#: 1 mm expressed in PDF points (1/72 inch).
_MM_TO_PT: float = 2.834645669

CompressionMode = Literal["auto", "jpeg", "png"]
OutputTarget = str | Path | BinaryIO


@dataclass
class PdfOverlayOptions:
    page_numbers: bool = False
    page_number_format: str = "Page {n} / {total}"
    header_text: str | None = None
    footer_text: str | None = None
    watermark: str | None = None
    watermark_opacity: float = 0.15
    margin_mm: float = 5.0


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


def _choose_auto_compression(img: Image.Image) -> Literal["jpeg", "png"]:
    """Pick a compact image encoding suitable for the image content."""
    if img.mode in {"RGBA", "LA"} or (img.mode == "P" and "transparency" in img.info):
        return "png"

    sample = img.convert("RGB")
    sample.thumbnail((128, 128))
    colors_count = sample.getcolors(maxcolors=4096)
    if colors_count is not None and len(colors_count) < 512:
        return "png"
    return "jpeg"


def _normalise_jpeg_image(img: Image.Image) -> Image.Image:
    """Convert a PIL image to an RGB image that can be encoded as JPEG."""
    if img.mode == "RGB":
        return img
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.getchannel("A"))
        return background
    return img.convert("RGB")


def _pil_to_reader(
    img: Image.Image,
    compression: CompressionMode = "auto",
    image_quality: int = 92,
) -> ImageReader:
    """Wrap a PIL image in a reportlab ``ImageReader``."""
    if compression not in {"auto", "jpeg", "png"}:
        raise ValueError("compression must be one of: auto, jpeg, png")
    if not 1 <= image_quality <= 100:
        raise ValueError("image_quality must be between 1 and 100")

    encoding = _choose_auto_compression(img) if compression == "auto" else compression
    buf = BytesIO()
    if encoding == "jpeg":
        jpeg_img = _normalise_jpeg_image(img)
        jpeg_img.save(buf, format="JPEG", quality=image_quality, optimize=True)
    else:
        img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _prepare_page_iterator(
    page_images: Iterable[Image.Image],
    require_total: bool,
) -> tuple[Image.Image, Iterator[Image.Image], int | None]:
    """Peek at an image iterable while preserving a replayable iterator."""
    iterator = iter(page_images)
    try:
        first = next(iterator)
    except StopIteration as exc:
        raise ValueError("page_images must not be empty") from exc

    total = len(page_images) if isinstance(page_images, Sized) else None
    if require_total and total is None:
        pages = [first, *iterator]
        return first, iter(pages), len(pages)

    return first, chain((first,), iterator), total


def _canvas_target(output: OutputTarget) -> tuple[str | BinaryIO, Path | BinaryIO]:
    """Return the reportlab target and the value to return from public APIs."""
    if hasattr(output, "write"):
        return output, output

    output_path = Path(output)
    return str(output_path), output_path


def _set_pdf_metadata(
    pdf_canvas: canvas.Canvas,
    title: str | None,
    author: str | None,
    subject: str | None,
    keywords: str | None,
) -> None:
    """Apply optional document metadata to a reportlab canvas."""
    if title is not None:
        pdf_canvas.setTitle(title)
    if author is not None:
        pdf_canvas.setAuthor(author)
    if subject is not None:
        pdf_canvas.setSubject(subject)
    if keywords is not None:
        pdf_canvas.setKeywords(keywords)


def _format_overlay_text(template: str, title: str | None) -> str:
    """Expand supported overlay placeholders."""
    return template.format(url="", title=title or "", date=date.today().isoformat())


def _draw_overlay(
    pdf_canvas: canvas.Canvas,
    overlay: PdfOverlayOptions | None,
    page_w_pt: float,
    page_h_pt: float,
    page_number: int,
    total_pages: int | None,
    title: str | None,
) -> None:
    """Render optional header, footer, page number, and watermark overlays."""
    if overlay is None:
        return

    margin = mm_to_points(overlay.margin_mm)
    pdf_canvas.saveState()

    if overlay.watermark:
        opacity = max(0.0, min(1.0, overlay.watermark_opacity))
        if hasattr(pdf_canvas, "setFillAlpha"):
            pdf_canvas.setFillAlpha(opacity)
        pdf_canvas.setFillColor(colors.grey)
        pdf_canvas.setFont("Helvetica-Bold", max(24, min(page_w_pt, page_h_pt) / 8))
        pdf_canvas.translate(page_w_pt / 2, page_h_pt / 2)
        pdf_canvas.rotate(45)
        pdf_canvas.drawCentredString(0, 0, overlay.watermark)
        pdf_canvas.restoreState()
        pdf_canvas.saveState()

    pdf_canvas.setFillColor(colors.black)
    pdf_canvas.setFont("Helvetica", 9)

    if overlay.header_text:
        header = _format_overlay_text(overlay.header_text, title)
        pdf_canvas.drawString(margin, page_h_pt - margin - 9, header)

    bottom_y = margin
    if overlay.page_numbers:
        page_text = overlay.page_number_format.format(n=page_number, total=total_pages or page_number)
        pdf_canvas.setFont("Helvetica", 8)
        pdf_canvas.drawCentredString(page_w_pt / 2, bottom_y, page_text)
        bottom_y += 11

    if overlay.footer_text:
        footer = _format_overlay_text(overlay.footer_text, title)
        pdf_canvas.setFont("Helvetica", 9)
        pdf_canvas.drawCentredString(page_w_pt / 2, bottom_y, footer)

    pdf_canvas.restoreState()


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
    page_images: Iterable[Image.Image],
    output_path: OutputTarget,
    paper_size: tuple[float, float] = (210, 297),
    dpi: int = 150,
    compression: CompressionMode = "auto",
    image_quality: int = 92,
    overlay: PdfOverlayOptions | None = None,
    title: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    keywords: str | None = None,
) -> Path | BinaryIO:
    """Build a PDF with fixed paper size from page images.

    Each image is scaled to fit the paper while maintaining aspect ratio and
    centred on the page.

    Parameters
    ----------
    page_images:
        PIL images, one per PDF page.
    output_path:
        Destination file path or writable binary stream.
    paper_size:
        ``(width_mm, height_mm)`` of every page.  Defaults to A4.
    dpi:
        Nominal DPI used for the PDF metadata (does not resample images).
    compression:
        Image encoding in the PDF. ``"auto"`` uses JPEG for photo-like images
        and PNG for screenshot-like images.
    image_quality:
        JPEG quality from 1 to 100.
    overlay:
        Optional page header, footer, page number, and watermark settings.
    title, author, subject, keywords:
        Optional PDF metadata.

    Returns
    -------
    Path | BinaryIO
        The destination path for path outputs, or the original stream.

    Raises
    ------
    ValueError
        If *page_images* is empty.
    """
    require_total = bool(
        overlay and overlay.page_numbers and "{total}" in overlay.page_number_format
    )
    _, pages, total_pages = _prepare_page_iterator(page_images, require_total=require_total)

    target, return_value = _canvas_target(output_path)
    page_w_pt = mm_to_points(paper_size[0])
    page_h_pt = mm_to_points(paper_size[1])

    c = canvas.Canvas(target, pagesize=(page_w_pt, page_h_pt))
    _set_pdf_metadata(c, title, author, subject, keywords)

    for page_number, img in enumerate(pages, start=1):
        reader = _pil_to_reader(img, compression=compression, image_quality=image_quality)
        x, y, draw_w, draw_h = _fit_image_on_page(img.width, img.height, page_w_pt, page_h_pt)
        c.drawImage(reader, x, y, width=draw_w, height=draw_h)
        _draw_overlay(c, overlay, page_w_pt, page_h_pt, page_number, total_pages, title)
        c.showPage()

    c.save()
    return return_value


def build_pdf_auto_size(
    page_images: Iterable[Image.Image],
    output_path: OutputTarget,
    dpi: int = 150,
    compression: CompressionMode = "auto",
    image_quality: int = 92,
    overlay: PdfOverlayOptions | None = None,
    title: str | None = None,
    author: str | None = None,
    subject: str | None = None,
    keywords: str | None = None,
) -> Path | BinaryIO:
    """Build a PDF where each page matches its image dimensions exactly.

    No fixed paper size is used — every page is sized so that the image fills
    it completely at the given *dpi*.

    Parameters
    ----------
    page_images:
        PIL images, one per PDF page.
    output_path:
        Destination file path or writable binary stream.
    dpi:
        Resolution used to convert pixel dimensions to physical size.
    compression:
        Image encoding in the PDF. ``"auto"`` uses JPEG for photo-like images
        and PNG for screenshot-like images.
    image_quality:
        JPEG quality from 1 to 100.
    overlay:
        Optional page header, footer, page number, and watermark settings.
    title, author, subject, keywords:
        Optional PDF metadata.

    Returns
    -------
    Path | BinaryIO
        The destination path for path outputs, or the original stream.

    Raises
    ------
    ValueError
        If *page_images* is empty.
    """
    require_total = bool(
        overlay and overlay.page_numbers and "{total}" in overlay.page_number_format
    )
    first, pages, total_pages = _prepare_page_iterator(page_images, require_total=require_total)

    # Use the first image to initialise the canvas; each page will override.
    target, return_value = _canvas_target(output_path)
    init_w = mm_to_points(px_to_mm(first.width, dpi))
    init_h = mm_to_points(px_to_mm(first.height, dpi))
    c = canvas.Canvas(target, pagesize=(init_w, init_h))
    _set_pdf_metadata(c, title, author, subject, keywords)

    for page_number, img in enumerate(pages, start=1):
        page_w_pt = mm_to_points(px_to_mm(img.width, dpi))
        page_h_pt = mm_to_points(px_to_mm(img.height, dpi))
        c.setPageSize((page_w_pt, page_h_pt))

        reader = _pil_to_reader(img, compression=compression, image_quality=image_quality)
        c.drawImage(reader, 0, 0, width=page_w_pt, height=page_h_pt)
        _draw_overlay(c, overlay, page_w_pt, page_h_pt, page_number, total_pages, title)
        c.showPage()

    c.save()
    return return_value
