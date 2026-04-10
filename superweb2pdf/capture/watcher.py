"""Directory watcher for SuperWeb2PDF.

Monitors a directory for new image files and auto-processes them into
PDFs via a caller-supplied callback.  Used by the ``--watch DIR`` CLI mode.
"""

from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    raise ImportError(
        "watchdog is required for --watch mode. Install: pip install watchdog"
    )

IMAGE_EXTENSIONS: set[str] = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}

DEBOUNCE_SECONDS: float = 1.0


class _ImageEventHandler(FileSystemEventHandler):
    """React to newly created image files in the watched directory."""

    def __init__(
        self,
        watch_dir: Path,
        output_dir: Path,
        process_fn: callable | None,
        verbose: bool,
        stats: dict[str, int],
    ) -> None:
        super().__init__()
        self._watch_dir = watch_dir
        self._output_dir = output_dir
        self._process_fn = process_fn
        self._verbose = verbose
        self._stats = stats
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------

    def on_created(self, event):  # noqa: ANN001
        if event.is_directory:
            return
        self._schedule(event.src_path)

    def on_moved(self, event):  # noqa: ANN001
        if event.is_directory:
            return
        self._schedule(event.dest_path)

    # ------------------------------------------------------------------

    def _schedule(self, path: str) -> None:
        """Debounce: wait before processing so the file finishes writing."""
        file_path = Path(path)

        if not self._is_eligible(file_path):
            return

        with self._lock:
            # Cancel any pending timer for the same file
            existing = self._timers.pop(str(file_path), None)
            if existing is not None:
                existing.cancel()

            timer = threading.Timer(DEBOUNCE_SECONDS, self._handle, args=[file_path])
            timer.daemon = True
            self._timers[str(file_path)] = timer
            timer.start()

    def _is_eligible(self, file_path: Path) -> bool:
        """Return True if *file_path* should be processed."""
        if file_path.name.startswith("."):
            return False

        if file_path.suffix.lower() not in IMAGE_EXTENSIONS:
            return False

        # Skip files inside any directory named "output"
        for parent in file_path.relative_to(self._watch_dir).parents:
            if parent.name == "output":
                return False

        return True

    def _handle(self, file_path: Path) -> None:
        """Process a single image file after the debounce delay."""
        with self._lock:
            self._timers.pop(str(file_path), None)

        if not file_path.exists():
            return

        output_pdf = self._output_dir / file_path.with_suffix(".pdf").name

        if self._verbose:
            print(f"  ⏳ Processing {file_path.name} …", file=sys.stderr)

        if self._process_fn is None:
            print(f"  (dry-run) {file_path} → {output_pdf}")
            with self._lock:
                self._stats["processed"] += 1
            return

        try:
            self._process_fn(str(file_path), str(output_pdf))
            with self._lock:
                self._stats["processed"] += 1
            if self._verbose:
                print(f"  ✓ {file_path.name} → {output_pdf.name}", file=sys.stderr)
        except Exception as exc:
            with self._lock:
                self._stats["failed"] += 1
            print(f"  ✗ {file_path.name}: {exc}", file=sys.stderr)

    def cancel_pending(self) -> None:
        """Cancel all pending debounce timers."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()


def watch_directory(
    watch_dir: str,
    output_dir: str | None = None,
    process_fn: callable = None,
    verbose: bool = False,
) -> None:
    """Watch *watch_dir* for new images and process them into PDFs.

    Blocks until interrupted with Ctrl-C.

    Args:
        watch_dir:  Directory to monitor for new image files.
        output_dir: Where to save generated PDFs.  Defaults to a sibling
                    ``output/`` directory next to *watch_dir*.
        process_fn: Callback ``(image_path: str, output_pdf: str) -> None``.
                    If *None*, runs in dry-run mode (prints actions only).
        verbose:    Print filesystem events to stderr.
    """
    watch_path = Path(watch_dir).resolve()

    if not watch_path.is_dir():
        print(f"Error: watch directory not found: {watch_path}", file=sys.stderr)
        sys.exit(1)

    if output_dir is not None:
        out_path = Path(output_dir).resolve()
    else:
        out_path = watch_path.parent / "output"

    os.makedirs(out_path, exist_ok=True)

    stats: dict[str, int] = {"processed": 0, "failed": 0}

    handler = _ImageEventHandler(
        watch_dir=watch_path,
        output_dir=out_path,
        process_fn=process_fn,
        verbose=verbose,
        stats=stats,
    )

    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=False)
    observer.start()

    print(
        f"👀 Watching {watch_path}\n"
        f"   Output → {out_path}\n"
        f"   Press Ctrl+C to stop.",
        file=sys.stderr,
    )

    try:
        while observer.is_alive():
            observer.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        handler.cancel_pending()
        observer.join()

        total = stats["processed"] + stats["failed"]
        print(
            f"\n🛑 Stopped. {stats['processed']} processed, "
            f"{stats['failed']} failed ({total} total).",
            file=sys.stderr,
        )
