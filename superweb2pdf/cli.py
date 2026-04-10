"""CLI entry point for SuperWeb2PDF (superweb2pdf)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


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
    out.add_argument("-o", "--output", metavar="FILE", help="Output PDF path")
    out.add_argument(
        "--open", action="store_true", help="Open PDF after generation (macOS)"
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
        args._cdp_current_page = True
    else:
        args._cdp_current_page = getattr(args, '_cdp_current_page', False)

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


def main(argv: list[str] | None = None) -> None:
    """CLI entry point."""
    try:
        args = parse_args(argv)
    except SystemExit:
        raise

    # Lazy imports so argparse --help stays fast
    from superweb2pdf.capture.file_input import capture_from_file, capture_from_files
    from superweb2pdf.core.image_utils import crop_pages, resize_to_max_width
    from superweb2pdf.core.pdf_builder import (
        build_pdf,
        build_pdf_auto_size,
        parse_paper_size,
    )
    from superweb2pdf.core.splitter import split_image

    try:
        # 1. Capture / load image
        if args.watch:
            # --watch mode runs a long-lived loop; handled separately
            _run_watch_mode(args)
            return

        if args.image:
            if args.verbose:
                print(f"Loading {args.image} …", file=sys.stderr)
            image = capture_from_file(args.image)
        elif args.images:
            if args.verbose:
                print(f"Loading images matching {args.images} …", file=sys.stderr)
            image = capture_from_files(args.images)
        elif args.current_tab:
            if args.verbose:
                print("Capturing Chrome current tab …", file=sys.stderr)
            from superweb2pdf.capture.applescript import capture_current_tab
            image = capture_current_tab(
                scroll_delay_ms=args.scroll_delay,
                verbose=args.verbose,
            )
        elif args.url and args.cdp:
            if args.verbose:
                print(f"Capturing {args.url} via CDP (port {args.cdp}) …", file=sys.stderr)
            from superweb2pdf.capture.cdp import capture_via_cdp
            image = capture_via_cdp(
                url=args.url,
                cdp_port=args.cdp,
                scroll_delay_ms=args.scroll_delay,
                verbose=args.verbose,
            )
        elif args.url:
            if args.verbose:
                print(f"Capturing {args.url} (headless) …", file=sys.stderr)
            from superweb2pdf.capture.headless import capture_url
            image = capture_url(
                url=args.url,
                scroll_delay_ms=args.scroll_delay,
                verbose=args.verbose,
            )
        elif getattr(args, '_cdp_current_page', False):
            if args.verbose:
                print(f"Capturing current CDP page (port {args.cdp}) …", file=sys.stderr)
            from superweb2pdf.capture.cdp import capture_via_cdp
            image = capture_via_cdp(
                url=None,
                cdp_port=args.cdp,
                scroll_delay_ms=args.scroll_delay,
                verbose=args.verbose,
            )
        else:
            print("Error: no input source specified.", file=sys.stderr)
            sys.exit(1)

        if args.verbose:
            print(f"Image size: {image.width}×{image.height}", file=sys.stderr)

        # 2. Resize if needed
        if args.max_width:
            image = resize_to_max_width(image, args.max_width)
            if args.verbose:
                print(f"Resized to {image.width}×{image.height}", file=sys.stderr)

        # 3. Calculate max page height
        if args.max_height:
            max_page_height = args.max_height
        else:
            paper_w, paper_h = parse_paper_size(args.paper)
            aspect = paper_h / paper_w
            max_page_height = int(image.width * aspect)

        if args.verbose:
            print(f"Max page height: {max_page_height}px", file=sys.stderr)

        # 4. Split
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

        # 5. Generate PDF
        output = args.output or auto_output_name(args)
        os.makedirs(Path(output).parent or ".", exist_ok=True)

        if args.auto_size:
            build_pdf_auto_size(page_images, output, dpi=args.dpi)
        else:
            paper = parse_paper_size(args.paper)
            build_pdf(page_images, output, paper_size=paper, dpi=args.dpi)

        print(f"✓ Saved {len(page_images)} pages to {output}")

        # 6. Open if requested
        if args.open:
            subprocess.run(["open", output], check=False)

    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
