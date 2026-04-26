"""High-level conversion API for SuperWeb2PDF."""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

from PIL import Image

from superweb2pdf.backends import CaptureBackend, get_default_registry
from superweb2pdf.errors import CaptureError, ConfigurationError, RenderError, SplitError
from superweb2pdf.options import WebToPdfOptions
from superweb2pdf.progress import ProgressCallback, ProgressEvent, ProgressStage
from superweb2pdf.result import ConversionResult, PageInfo, WarningInfo

logger = logging.getLogger(__name__)

__all__ = [
    "convert",
    "convert_image",
    "convert_url",
    "convert_pil",
]


def _emit(
    callback: ProgressCallback | None,
    stage: ProgressStage,
    message: str,
    **kw: object,
) -> None:
    if callback:
        callback(ProgressEvent(stage=stage, message=message, **kw))


def _safe_filename_stem(value: str, fallback: str = "superweb2pdf") -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-_")
    return stem[:80] or fallback


def _auto_output_path(source: str) -> Path:
    """Generate a PDF output path from a source string."""
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    if source == "<PIL.Image>":
        stem = "pil-image"
    else:
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            path_part = Path(parsed.path).stem if parsed.path and parsed.path != "/" else "page"
            stem = _safe_filename_stem(f"{parsed.netloc}-{path_part}")
        else:
            stem = _safe_filename_stem(Path(source).stem or source)
    return Path(f"{stem}-{timestamp}.pdf")


def _select_backend(source: str, options: WebToPdfOptions) -> CaptureBackend:
    registry = get_default_registry()
    if options.capture.backend == "auto":
        return registry.auto_select(source)

    backend_name = "mac-chrome" if options.capture.backend == "macos" else options.capture.backend
    backend = registry.get(backend_name)
    if backend is None:
        raise ConfigurationError(f"Unknown backend: {options.capture.backend}")
    if not backend.supports(source):
        raise ConfigurationError(f"Backend {options.capture.backend!r} does not support {source!r}")
    if not backend.available:
        hint = f" Install with: {backend.install_hint}" if backend.install_hint else ""
        raise CaptureError(f"Capture backend {backend.name!r} is not available.{hint}")
    return backend


def convert(
    source: str | Path | Image.Image,
    output: str | Path | BinaryIO | None = None,
    *,
    options: WebToPdfOptions | None = None,
    progress: ProgressCallback | None = None,
) -> ConversionResult:
    """Convert a web page, image file, or PIL Image to a paginated PDF.

    Parameters
    ----------
    source:
        - str/Path to a local image file or glob pattern
        - HTTP/HTTPS URL (requires capture backend)
        - "current-tab" (macOS Chrome capture)
        - PIL Image object
    output:
        - str/Path for file output
        - BinaryIO for in-memory output
        - None for auto-generated filename
    options:
        Conversion options. Uses defaults if None.
    progress:
        Optional callback for progress events.

    Returns
    -------
    ConversionResult with page count, output path, etc.
    """
    start_time = time.monotonic()
    options = options or WebToPdfOptions()
    warnings: list[WarningInfo] = []

    if isinstance(source, Image.Image):
        image = source
        source_str = "<PIL.Image>"
        backend_name = "pil"
    else:
        source_str = str(source)
        _emit(progress, "capture", f"Capturing {source_str}...")
        try:
            backend = _select_backend(source_str, options)
            backend_name = backend.name
            image = backend.capture(
                source_str,
                scroll_delay_ms=options.capture.scroll_delay_ms,
                viewport_width=options.capture.viewport_width,
                viewport_height=options.capture.viewport_height,
                cdp_port=options.capture.cdp_port,
                verbose=False,
            )
        except ConfigurationError:
            raise
        except CaptureError:
            raise
        except Exception as exc:
            raise CaptureError(f"Capture failed: {exc}") from exc

    _emit(progress, "preprocess", "Preprocessing image...")
    if options.split.max_width and image.width > options.split.max_width:
        from superweb2pdf.core.image_utils import resize_to_max_width

        image = resize_to_max_width(image, options.split.max_width)
        logger.info("Resized to %dx%d", image.width, image.height)

    _emit(progress, "split", "Splitting image...")
    try:
        from superweb2pdf.core.image_utils import crop_pages
        from superweb2pdf.core.pdf_builder import parse_paper_size
        from superweb2pdf.core.splitter import split_image

        if options.split.max_height:
            max_page_height = options.split.max_height
        else:
            paper_w, paper_h = parse_paper_size(options.pdf.paper)
            aspect = paper_h / paper_w
            max_page_height = int(image.width * aspect)

        if max_page_height <= 0:
            raise ValueError(f"max_page_height must be positive, got {max_page_height}")

        if options.split.mode == "none":
            page_images = [image]
            hard_cut_set: set[int] = set()
        elif options.split.mode == "fixed":
            split_pts = list(range(max_page_height, image.height, max_page_height))
            page_images = crop_pages(image, split_pts)
            hard_cut_set = set(range(len(page_images)))
        else:
            extrema = image.convert("RGB").getextrema()
            if all(lo == hi for lo, hi in extrema):
                split_pts = list(range(max_page_height, image.height, max_page_height))
                page_images = crop_pages(image, split_pts)
                hard_cut_set = set(range(len(page_images)))
                warnings.append(
                    WarningInfo(
                        code="uniform_image",
                        message="Image is uniform; used fixed pagination instead of smart splitting.",
                    )
                )
            else:
                result = split_image(
                    image,
                    max_page_height,
                    min_blank_band=options.split.min_blank_band,
                    tolerance=options.split.blank_threshold,
                    search_ratio=options.split.search_ratio,
                )
                page_images = crop_pages(image, result.split_points)
                hard_cut_set = set(result.hard_cuts)
    except Exception as exc:
        raise SplitError(f"Split failed: {exc}") from exc

    _emit(progress, "render", f"Rendering {len(page_images)} pages...")
    output_path: Path | None
    try:
        from superweb2pdf.core.pdf_builder import PdfOverlayOptions, build_pdf, build_pdf_auto_size

        overlay = (
            PdfOverlayOptions(
                page_numbers=options.pdf.page_numbers,
                header_text=options.pdf.header_text,
                footer_text=options.pdf.footer_text,
                watermark=options.pdf.watermark,
            )
            if any(
                [
                    options.pdf.page_numbers,
                    options.pdf.header_text,
                    options.pdf.footer_text,
                    options.pdf.watermark,
                ]
            )
            else None
        )

        if output is None:
            output_path = _auto_output_path(source_str)
            target: str | Path | BinaryIO = output_path
        elif isinstance(output, (str, Path)):
            output_path = Path(output)
            os.makedirs(output_path.parent or Path("."), exist_ok=True)
            target = output_path
        else:
            output_path = None
            target = output

        if options.pdf.auto_size:
            build_pdf_auto_size(
                page_images,
                target,
                dpi=options.pdf.dpi,
                compression=options.pdf.compression,
                image_quality=options.pdf.image_quality,
                overlay=overlay,
                title=options.pdf.title,
                author=options.pdf.author,
            )
        else:
            paper = parse_paper_size(options.pdf.paper)
            build_pdf(
                page_images,
                target,
                paper_size=paper,
                dpi=options.pdf.dpi,
                compression=options.pdf.compression,
                image_quality=options.pdf.image_quality,
                overlay=overlay,
                title=options.pdf.title,
                author=options.pdf.author,
            )
    except Exception as exc:
        raise RenderError(f"Render failed: {exc}") from exc

    pages = [
        PageInfo(index=i, width_px=img.width, height_px=img.height, hard_cut=(i in hard_cut_set))
        for i, img in enumerate(page_images)
    ]

    file_size = None
    if output_path and output_path.exists():
        file_size = output_path.stat().st_size
    elif hasattr(output, "tell") and hasattr(output, "seek"):
        pos = output.tell()
        output.seek(0, 2)
        file_size = output.tell()
        output.seek(pos)

    _emit(progress, "done", f"Done — {len(pages)} pages")

    return ConversionResult(
        output_path=output_path,
        page_count=len(pages),
        source=source_str,
        backend=backend_name,
        pages=pages,
        warnings=warnings,
        file_size_bytes=file_size,
        elapsed_seconds=time.monotonic() - start_time,
    )


def convert_image(
    image_path: str | Path,
    output: str | Path | BinaryIO | None = None,
    *,
    options: WebToPdfOptions | None = None,
    progress: ProgressCallback | None = None,
) -> ConversionResult:
    """Convert a local image file to PDF. Shortcut for convert() with a file path."""
    return convert(image_path, output, options=options, progress=progress)


def convert_url(
    url: str,
    output: str | Path | BinaryIO | None = None,
    *,
    options: WebToPdfOptions | None = None,
    progress: ProgressCallback | None = None,
) -> ConversionResult:
    """Capture a URL and convert to PDF. Shortcut for convert() with a URL."""
    return convert(url, output, options=options, progress=progress)


def convert_pil(
    image: Image.Image,
    output: str | Path | BinaryIO | None = None,
    *,
    options: WebToPdfOptions | None = None,
    progress: ProgressCallback | None = None,
) -> ConversionResult:
    """Convert a PIL Image directly to PDF."""
    return convert(image, output, options=options, progress=progress)
