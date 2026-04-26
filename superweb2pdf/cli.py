"""CLI 入口 — SuperWeb2PDF 命令行工具"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from superweb2pdf.options import WebToPdfOptions
    from superweb2pdf.progress import ProgressCallback

logger = logging.getLogger(__name__)


def auto_output_name(args: argparse.Namespace) -> str:
    """Derive output PDF name from the input source."""
    if args.image:
        return str(Path(args.image).with_suffix(".pdf"))
    if args.images:
        pattern = args.images
        base = Path(pattern).stem.replace("*", "output")
        parent = Path(pattern).parent
        return str(parent / f"{base}.pdf")
    if args.current_tab or args.url:
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        if args.url:
            from urllib.parse import urlparse

            host = urlparse(args.url).hostname or "page"
            return f"superweb2pdf-{host}-{ts}.pdf"
        return f"capture-{ts}.pdf"
    return "output.pdf"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Build and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="superweb2pdf",
        description="Convert full-page web screenshots into intelligently paginated PDFs.",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    # --- Capture options (mutually exclusive) ---
    capture = parser.add_argument_group("Capture options")
    mx = capture.add_mutually_exclusive_group()
    mx.add_argument(
        "--current-tab",
        action="store_true",
        help="Capture Chrome's current tab via AppleScript (macOS)",
    )
    mx.add_argument("--image", metavar="FILE", help="Input a single long screenshot")
    mx.add_argument("--images", metavar="PATTERN", help="Input multiple screenshots (glob pattern)")
    mx.add_argument("--url", metavar="URL", help="Capture a URL (headless or CDP mode)")
    mx.add_argument("--watch", metavar="DIR", help="Watch directory for new images")

    # CDP option (used with --url)
    capture.add_argument(
        "--cdp",
        type=int,
        metavar="PORT",
        help="Connect via CDP to Chrome on PORT (use with --url, or alone to capture current page)",
    )
    capture.add_argument(
        "--backend",
        choices=["auto", "file", "headless", "cdp", "macos"],
        default="auto",
        help="Capture backend to use (default: auto)",
    )

    # --- Processing options ---
    proc = parser.add_argument_group("Processing options")
    proc.add_argument("--max-width", type=int, metavar="PX", help="Limit maximum width in pixels")
    proc.add_argument("--max-height", type=int, metavar="PX", help="Max page height in pixels")
    proc.add_argument(
        "--paper",
        default="a4",
        metavar="SIZE",
        help="Paper size: a4, a3, letter, legal, or WxH in mm (default: a4)",
    )
    proc.add_argument("--dpi", type=int, default=150, metavar="N", help="Output DPI (default: 150)")
    proc.add_argument(
        "--split",
        choices=["smart", "fixed", "none"],
        default="smart",
        help="Split mode (default: smart)",
    )
    proc.add_argument(
        "--blank-threshold",
        type=int,
        default=10,
        metavar="N",
        help="Blank detection color tolerance (default: 10)",
    )
    proc.add_argument(
        "--min-blank-band",
        type=int,
        default=5,
        metavar="N",
        help="Minimum blank band height in px (default: 5)",
    )
    proc.add_argument(
        "--scroll-delay",
        type=int,
        default=800,
        metavar="MS",
        help="Scroll delay for capture modes in ms (default: 800)",
    )
    proc.add_argument(
        "--auto-size",
        action="store_true",
        help="Auto-size pages to match content instead of fixed paper",
    )

    # --- Output options ---
    out = parser.add_argument_group("Output")
    out.add_argument("-o", "--output", metavar="FILE", help="Output PDF path")
    out.add_argument("--open", action="store_true", help="Open PDF after generation")
    out.add_argument("--json", action="store_true", help="Output result as JSON")
    out.add_argument("--page-numbers", action="store_true", help="Add page numbers to PDF")
    out.add_argument("-v", "--verbose", action="store_true", help="Show detailed progress")

    args = parser.parse_args(argv)

    if args.version:
        return args

    # Require at least one capture source
    if not any([args.image, args.images, args.current_tab, args.url, args.watch]):
        if args.cdp:
            pass  # --cdp alone captures the current CDP page
        else:
            parser.error(
                "one capture option is required (--image, --images, --current-tab, --url, --watch, or --cdp)"
            )

    # --cdp without --url means "capture current CDP page"
    if args.cdp and not args.url:
        args._cdp_current_page = True
    else:
        args._cdp_current_page = getattr(args, "_cdp_current_page", False)

    # Validate numeric arguments
    if args.max_width is not None and args.max_width <= 0:
        parser.error("--max-width must be a positive integer")
    if args.max_height is not None and args.max_height <= 0:
        parser.error("--max-height must be a positive integer")
    if args.dpi <= 0:
        parser.error("--dpi must be a positive integer")
    if args.min_blank_band <= 0:
        parser.error("--min-blank-band must be a positive integer")
    if args.blank_threshold < 0:
        parser.error("--blank-threshold must be non-negative")
    if args.scroll_delay < 0:
        parser.error("--scroll-delay must be non-negative")
    if args.cdp is not None and args.cdp <= 0:
        parser.error("--cdp port must be a positive integer")

    return args


def _run_watch_mode(args: argparse.Namespace) -> None:
    """Run the --watch directory watcher loop."""
    from superweb2pdf.capture.file_input import capture_from_file
    from superweb2pdf.capture.watcher import watch_directory
    from superweb2pdf.core.image_utils import crop_pages, resize_to_max_width
    from superweb2pdf.core.pdf_builder import (
        build_pdf,
        build_pdf_auto_size,
        parse_paper_size,
    )
    from superweb2pdf.core.splitter import split_image

    def process_image(image_path: str, output_pdf: str) -> None:
        """Process a single image file into a PDF."""
        if args.verbose:
            print(f"Processing {image_path} …", file=sys.stderr)
        image = capture_from_file(image_path)

        if args.max_width:
            image = resize_to_max_width(image, args.max_width)

        if args.max_height:
            max_page_height = args.max_height
        else:
            paper_w, paper_h = parse_paper_size(args.paper)
            aspect = paper_h / paper_w
            max_page_height = int(image.width * aspect)

        if args.split == "none":
            page_images = [image]
        elif args.split == "fixed":
            split_pts = list(range(max_page_height, image.height, max_page_height))
            page_images = crop_pages(image, split_pts)
        else:
            result = split_image(
                image,
                max_page_height,
                min_blank_band=args.min_blank_band,
                tolerance=args.blank_threshold,
            )
            page_images = crop_pages(image, result.split_points)

        if args.auto_size:
            build_pdf_auto_size(page_images, output_pdf, dpi=args.dpi)
        else:
            paper = parse_paper_size(args.paper)
            build_pdf(page_images, output_pdf, paper_size=paper, dpi=args.dpi)

        print(f"✓ {Path(image_path).name} → {Path(output_pdf).name} ({len(page_images)} pages)")

    watch_directory(
        watch_dir=args.watch,
        output_dir=args.output,
        process_fn=process_image,
        verbose=args.verbose,
    )


def _infer_backend(args: argparse.Namespace) -> str:
    """Infer the capture backend from CLI args.

    If the user explicitly set --backend, use that.  Otherwise, --cdp with
    --url implies the cdp backend so the port is respected.
    """
    explicit = getattr(args, "backend", "auto") or "auto"
    if explicit != "auto":
        return explicit
    if args.cdp and args.url:
        return "cdp"
    return "auto"


def _build_options(args: argparse.Namespace) -> WebToPdfOptions:
    """Convert CLI args to WebToPdfOptions."""
    from superweb2pdf.options import CaptureOptions, PdfOptions, SplitOptions, WebToPdfOptions

    capture = CaptureOptions(
        backend=_infer_backend(args),
        scroll_delay_ms=args.scroll_delay,
        cdp_port=args.cdp or 9222,
    )
    split = SplitOptions(
        mode=args.split,
        max_width=args.max_width,
        max_height=args.max_height,
        blank_threshold=args.blank_threshold,
        min_blank_band=args.min_blank_band,
    )
    pdf = PdfOptions(
        paper=args.paper,
        dpi=args.dpi,
        auto_size=args.auto_size,
        page_numbers=getattr(args, "page_numbers", False),
    )
    return WebToPdfOptions(capture=capture, split=split, pdf=pdf)


def _determine_source(args: argparse.Namespace) -> str:
    """Extract the source string from CLI args."""
    if args.image:
        return args.image
    if args.images:
        return args.images
    if args.current_tab:
        return "current-tab"
    if args.url:
        return args.url
    if getattr(args, "_cdp_current_page", False):
        return "cdp://current"
    raise SystemExit("Error: no input source specified.")


def _make_progress_callback(verbose: bool) -> ProgressCallback | None:
    """Create a stderr progress callback for verbose mode."""
    if not verbose:
        return None

    def _progress(event) -> None:
        parts = [f"[{event.stage}]", event.message]
        if event.percent is not None:
            parts.append(f"({event.percent:.0f}%)")
        elif event.current is not None and event.total is not None:
            parts.append(f"({event.current}/{event.total})")
        logger.info(" ".join(parts))

    return _progress


def _open_file(path: Path | None) -> None:
    """Open a file with the system's default viewer."""
    if path is None:
        return
    import subprocess

    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform.startswith("linux"):
        subprocess.run(["xdg-open", str(path)], check=False)
    elif sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        logger.warning("Cannot open file automatically on this platform")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    try:
        args = parse_args(argv)
    except SystemExit:
        raise

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(message)s",
        stream=sys.stderr,
    )

    if getattr(args, "version", False):
        from superweb2pdf import __version__

        print(f"superweb2pdf {__version__}")
        return

    if args.watch:
        _run_watch_mode(args)
        return

    options = _build_options(args)
    source = _determine_source(args)
    progress_cb = _make_progress_callback(args.verbose) if args.verbose else None

    from superweb2pdf.api import convert
    from superweb2pdf.errors import SuperWeb2PDFError

    try:
        result = convert(
            source, args.output or auto_output_name(args), options=options, progress=progress_cb
        )
    except SuperWeb2PDFError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)

    if args.json:
        import json

        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(f"✓ Saved {result.page_count} pages to {result.output_path}")

    if args.open:
        _open_file(result.output_path)


if __name__ == "__main__":
    main()
