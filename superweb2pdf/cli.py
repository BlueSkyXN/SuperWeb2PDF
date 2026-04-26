# -*- coding: utf-8 -*-
"""CLI 入口 — SuperWeb2PDF 命令行工具"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PureWindowsPath


def _package_version() -> str:
    """Return the installed package version, with a source-tree fallback."""
    try:
        return version("superweb2pdf")
    except PackageNotFoundError:
        from superweb2pdf import __version__

        return __version__


def _path_for_user_input(value: str) -> Path | PureWindowsPath:
    """Return a path object that preserves Windows paths during string parsing.

    ``Path`` uses the current platform's path flavour.  On POSIX, a Windows
    path such as ``C:\\screens\\*.png`` would otherwise be treated as a single
    filename containing backslashes, which produces poor automatic output names.
    """
    windows_path = PureWindowsPath(value)
    if windows_path.drive or "\\" in value:
        return windows_path
    return Path(value)


def auto_output_name(args: argparse.Namespace) -> str:
    """Derive output PDF name from the input source."""
    if args.image:
        return str(_path_for_user_input(args.image).with_suffix(".pdf"))
    if args.images:
        pattern = args.images
        pattern_path = _path_for_user_input(pattern)
        base = pattern_path.stem.replace("*", "output") or "output"
        parent = pattern_path.parent
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
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_package_version()}",
        help="Show version and exit",
    )

    # --- Capture options (mutually exclusive) ---
    capture = parser.add_argument_group("Capture options")
    mx = capture.add_mutually_exclusive_group()
    mx.add_argument(
        "--current-tab",
        action="store_true",
        help="Capture Chrome's current tab via AppleScript (macOS)",
    )
    mx.add_argument("--image", metavar="FILE", help="Input a single long screenshot")
    mx.add_argument(
        "--images", metavar="PATTERN", help="Input multiple screenshots (glob pattern)"
    )
    mx.add_argument("--url", metavar="URL", help="Capture a URL (headless or CDP mode)")
    mx.add_argument("--watch", metavar="DIR", help="Watch directory for new images")

    # CDP option (used with --url)
    capture.add_argument(
        "--cdp",
        type=int,
        metavar="PORT",
        help="Connect via CDP to Chrome on PORT (use with --url, or alone to capture current page)",
    )

    # --- Processing options ---
    proc = parser.add_argument_group("Processing options")
    proc.add_argument(
        "--max-width", type=int, metavar="PX", help="Limit maximum width in pixels"
    )
    proc.add_argument(
        "--max-height", type=int, metavar="PX", help="Max page height in pixels"
    )
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
    out.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help="Output PDF path (directory when used with --watch)",
    )
    out.add_argument(
        "--open", action="store_true", help="Open PDF after generation"
    )
    out.add_argument("-v", "--verbose", action="store_true", help="Show detailed progress")

    args = parser.parse_args(argv)

    # Require at least one capture source
    if not any([args.image, args.images, args.current_tab, args.url, args.watch]):
        if args.cdp:
            pass  # --cdp alone captures the current CDP page
        else:
            parser.error("one capture option is required (--image, --images, --current-tab, --url, --watch, or --cdp)")

    # --cdp without --url means "capture current CDP page"
    if args.cdp and not args.url:
        args.capture_mode = "cdp-current"
    elif args.url and args.cdp:
        args.capture_mode = "url-cdp"
    elif args.url:
        args.capture_mode = "url"
    elif args.current_tab:
        args.capture_mode = "current-tab"
    elif args.image:
        args.capture_mode = "image"
    elif args.images:
        args.capture_mode = "images"
    elif args.watch:
        args.capture_mode = "watch"
    else:
        args.capture_mode = None

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

    # Validate paper size at parse time so users get an argparse-style message.
    from superweb2pdf.core.pdf_builder import parse_paper_size

    try:
        parse_paper_size(args.paper)
    except ValueError as exc:
        parser.error(f"--paper: {exc}")

    if args.current_tab and sys.platform != "darwin":
        parser.error(
            "--current-tab is only supported on macOS. "
            "Use --url for headless capture or --cdp PORT to capture an existing browser page."
        )

    if args.images:
        from superweb2pdf.core.image_utils import glob_images

        if not glob_images(args.images):
            parser.error(
                f"--images pattern matched no supported image files: {args.images!r}. "
                "Check the path/pattern and quote wildcards if your shell expands them."
            )

    if args.watch and args.output:
        output_path = Path(args.output)
        if output_path.exists() and not output_path.is_dir():
            parser.error(
                "--output must be a directory when used with --watch; "
                f"got existing file: {args.output}"
            )
        if not output_path.exists() and output_path.suffix.lower() == ".pdf":
            parser.error(
                "--output must be a directory when used with --watch; "
                f"got file-like path: {args.output}"
            )

    return args


def _process_image_to_pdf(
    image,  # noqa: ANN001 - keep PIL as an optional/lazy runtime dependency here
    output: str | Path,
    args: argparse.Namespace,
) -> int:
    """Apply common image processing and write a PDF.

    Returns the number of PDF pages generated.
    """
    from superweb2pdf.core.image_utils import crop_pages, resize_to_max_width
    from superweb2pdf.core.pdf_builder import (
        build_pdf,
        build_pdf_auto_size,
        parse_paper_size,
    )
    from superweb2pdf.core.splitter import split_image

    if args.verbose:
        print(f"Image size: {image.width}×{image.height}", file=sys.stderr)

    if args.max_width:
        image = resize_to_max_width(image, args.max_width)
        if args.verbose:
            print(f"Resized to {image.width}×{image.height}", file=sys.stderr)

    if args.max_height:
        max_page_height = args.max_height
    else:
        paper_w, paper_h = parse_paper_size(args.paper)
        aspect = paper_h / paper_w
        max_page_height = int(image.width * aspect)

    if args.verbose:
        print(f"Max page height: {max_page_height}px", file=sys.stderr)

    if args.split == "none":
        page_images = [image]
    elif args.split == "fixed":
        split_pts = list(range(max_page_height, image.height, max_page_height))
        page_images = crop_pages(image, split_pts)
    else:  # smart
        result = split_image(
            image,
            max_page_height,
            min_blank_band=args.min_blank_band,
            tolerance=args.blank_threshold,
        )
        page_images = crop_pages(image, result.split_points)
        if args.verbose:
            print(
                f"Split into {len(page_images)} pages "
                f"({len(result.hard_cuts)} hard cuts)",
                file=sys.stderr,
            )

    output_path = Path(output)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(
            f"Cannot create output directory {output_path.parent}: "
            f"{exc.strerror or exc}"
        ) from exc

    if args.auto_size:
        build_pdf_auto_size(page_images, output_path, dpi=args.dpi)
    else:
        paper = parse_paper_size(args.paper)
        build_pdf(page_images, output_path, paper_size=paper, dpi=args.dpi)

    return len(page_images)


def _capture_image(args: argparse.Namespace):
    """Capture or load a single source image according to parsed CLI args."""
    if args.image:
        if args.verbose:
            print(f"Loading {args.image} …", file=sys.stderr)
        from superweb2pdf.capture.file_input import capture_from_file

        return capture_from_file(args.image)

    if args.images:
        if args.verbose:
            print(f"Loading images matching {args.images} …", file=sys.stderr)
        from superweb2pdf.capture.file_input import capture_from_files

        return capture_from_files(args.images)

    if args.current_tab:
        if args.verbose:
            print("Capturing Chrome current tab …", file=sys.stderr)
        from superweb2pdf.capture.applescript import capture_current_tab

        return capture_current_tab(
            scroll_delay_ms=args.scroll_delay,
            verbose=args.verbose,
        )

    if args.capture_mode == "url-cdp":
        if args.verbose:
            print(f"Capturing {args.url} via CDP (port {args.cdp}) …", file=sys.stderr)
        from superweb2pdf.capture.cdp import capture_via_cdp

        return capture_via_cdp(
            url=args.url,
            cdp_port=args.cdp,
            scroll_delay_ms=args.scroll_delay,
            verbose=args.verbose,
        )

    if args.url:
        if args.verbose:
            print(f"Capturing {args.url} (headless) …", file=sys.stderr)
        from superweb2pdf.capture.headless import capture_url

        return capture_url(
            url=args.url,
            scroll_delay_ms=args.scroll_delay,
            verbose=args.verbose,
        )

    if args.capture_mode == "cdp-current":
        if args.verbose:
            print(f"Capturing current CDP page (port {args.cdp}) …", file=sys.stderr)
        from superweb2pdf.capture.cdp import capture_via_cdp

        return capture_via_cdp(
            url=None,
            cdp_port=args.cdp,
            scroll_delay_ms=args.scroll_delay,
            verbose=args.verbose,
        )

    raise ValueError(
        "No input source specified. Use --image, --images, --url, --current-tab, "
        "--watch, or --cdp PORT."
    )


def _open_pdf(output: str | Path) -> None:
    """Open a generated PDF using the current platform's default application."""
    output = str(output)
    try:
        if sys.platform == "win32":
            os.startfile(output)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", output], check=True)
        else:
            subprocess.run(["xdg-open", output], check=True)
    except FileNotFoundError as exc:
        opener = "xdg-open" if sys.platform.startswith("linux") else "system opener"
        print(
            f"Warning: PDF was saved but could not be opened automatically "
            f"({opener} not found). Open it manually: {output}",
            file=sys.stderr,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            f"Warning: PDF was saved but could not be opened automatically: {exc}",
            file=sys.stderr,
        )


def _run_watch_mode(args: argparse.Namespace) -> None:
    """Run the --watch directory watcher loop."""
    from superweb2pdf.capture.file_input import capture_from_file
    from superweb2pdf.capture.watcher import watch_directory

    def process_image(image_path: str, output_pdf: str) -> None:
        """Process a single image file into a PDF."""
        if args.verbose:
            print(f"Processing {image_path} …", file=sys.stderr)
        image = capture_from_file(image_path)
        page_count = _process_image_to_pdf(image, output_pdf, args)
        print(
            f"✓ {Path(image_path).name} → {Path(output_pdf).name} ({page_count} pages)",
            file=sys.stderr,
        )

    watch_directory(
        watch_dir=args.watch,
        output_dir=args.output,
        process_fn=process_image,
        verbose=args.verbose,
    )


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    args = parse_args(argv)

    try:
        # 1. Capture / load image
        if args.watch:
            # --watch mode runs a long-lived loop; handled separately
            _run_watch_mode(args)
            return

        image = _capture_image(args)

        # 2. Generate PDF
        output = args.output or auto_output_name(args)
        page_count = _process_image_to_pdf(image, output, args)

        print(f"✓ Saved {page_count} pages to {output}")

        # 3. Open if requested
        if args.open:
            _open_pdf(output)

    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except PermissionError as exc:
        print(
            f"Error: permission denied: {exc}. "
            "Check the output directory permissions or choose a different --output path.",
            file=sys.stderr,
        )
        sys.exit(1)
    except OSError as exc:
        print(
            f"Error: filesystem error: {exc}. "
            "Check that the output path exists, is writable, and has enough free space.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (ValueError, RuntimeError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
