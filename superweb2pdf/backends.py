"""Capture backend protocol and registry."""

from __future__ import annotations

import glob
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse

from PIL import Image


@runtime_checkable
class CaptureBackend(Protocol):
    """Protocol that all capture backends must satisfy."""

    @property
    def name(self) -> str:
        """Human-readable backend name."""
        ...

    @property
    def available(self) -> bool:
        """Whether this backend's dependencies are installed and usable."""
        ...

    @property
    def install_hint(self) -> str:
        """Installation instructions if not available."""
        ...

    def supports(self, source: str) -> bool:
        """Whether this backend can handle the given source string."""
        ...

    def capture(self, source: str, **kwargs) -> Image.Image:
        """Capture source and return a PIL Image."""
        ...


@dataclass
class BackendInfo:
    """Availability metadata for a registered capture backend."""

    name: str
    available: bool
    install_hint: str


class BackendRegistry:
    """Registry of capture backends with auto-selection."""

    def __init__(self) -> None:
        self._backends: list[CaptureBackend] = []

    def register(self, backend: CaptureBackend) -> None:
        """Register a capture backend."""
        self._backends.append(backend)

    def get(self, name: str) -> CaptureBackend | None:
        """Return the backend named *name*, or ``None`` if it is not registered."""
        normalized = name.casefold()
        for backend in self._backends:
            if backend.name.casefold() == normalized:
                return backend
        return None

    def list_backends(self) -> list[BackendInfo]:
        """List registered backends and their availability."""
        return [
            BackendInfo(
                name=backend.name,
                available=backend.available,
                install_hint=backend.install_hint,
            )
            for backend in self._backends
        ]

    def auto_select(self, source: str) -> CaptureBackend:
        """Select the first available backend that supports *source*."""
        candidates = [backend for backend in self._backends if backend.supports(source)]
        for backend in candidates:
            if backend.available:
                return backend

        if candidates:
            hints = [backend.install_hint for backend in candidates if backend.install_hint]
            hint_text = f" Install with: {'; '.join(hints)}" if hints else ""
            names = ", ".join(backend.name for backend in candidates)
            raise RuntimeError(f"No available capture backend for {source!r}. Tried: {names}.{hint_text}")

        raise ValueError(f"No capture backend supports source: {source!r}")


def _is_http_url(source: str) -> bool:
    parsed = urlparse(source)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _has_glob_wildcards(source: str) -> bool:
    return glob.has_magic(source)


class FileBackend:
    """Capture backend for local image files, directories, and glob patterns."""

    @property
    def name(self) -> str:
        return "file"

    @property
    def available(self) -> bool:
        return True

    @property
    def install_hint(self) -> str:
        return ""

    def supports(self, source: str) -> bool:
        if _is_http_url(source):
            return False
        return Path(source).exists() or _has_glob_wildcards(source)

    def capture(self, source: str, **kwargs) -> Image.Image:
        """Capture local image input, dispatching by source type."""
        from superweb2pdf.capture.file_input import (
            capture_from_directory,
            capture_from_file,
            capture_from_files,
        )

        path = Path(source)
        if path.is_dir():
            return capture_from_directory(path)
        if _has_glob_wildcards(source):
            return capture_from_files(source)
        return capture_from_file(path)


class HeadlessBackend:
    """Capture backend for URLs using Playwright headless Chromium."""

    @property
    def name(self) -> str:
        return "headless"

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("playwright") is not None

    @property
    def install_hint(self) -> str:
        return "pip install superweb2pdf[capture] or pip install playwright && playwright install chromium"

    def supports(self, source: str) -> bool:
        return _is_http_url(source)

    def capture(self, source: str, **kwargs) -> Image.Image:
        """Capture an HTTP(S) URL via headless Chromium."""
        from superweb2pdf.capture.headless import capture_url

        return capture_url(source, **kwargs)


class CdpBackend:
    """Capture backend for URLs or the active tab via Chrome DevTools Protocol."""

    @property
    def name(self) -> str:
        return "cdp"

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("playwright") is not None

    @property
    def install_hint(self) -> str:
        return "pip install superweb2pdf[capture] or pip install playwright && playwright install chromium"

    def supports(self, source: str) -> bool:
        return source == "cdp://current" or _is_http_url(source)

    def capture(self, source: str, **kwargs) -> Image.Image:
        """Capture an HTTP(S) URL or the current CDP tab."""
        from superweb2pdf.capture.cdp import capture_via_cdp

        url = None if source == "cdp://current" else source
        return capture_via_cdp(url, **kwargs)


class MacChromeBackend:
    """Capture backend for the current macOS Chrome tab."""

    @property
    def name(self) -> str:
        return "mac-chrome"

    @property
    def available(self) -> bool:
        return sys.platform == "darwin" and importlib.util.find_spec("Quartz") is not None

    @property
    def install_hint(self) -> str:
        return "Requires macOS, Google Chrome, and pyobjc-framework-Quartz"

    def supports(self, source: str) -> bool:
        return source == "current-tab"

    def capture(self, source: str, **kwargs) -> Image.Image:
        """Capture Chrome's current tab on macOS."""
        from superweb2pdf.capture.applescript import capture_current_tab

        return capture_current_tab(**kwargs)


_default_registry: BackendRegistry | None = None


def get_default_registry() -> BackendRegistry:
    """Get or create the default backend registry with all built-in backends."""
    global _default_registry
    if _default_registry is None:
        _default_registry = BackendRegistry()
        _default_registry.register(FileBackend())
        _default_registry.register(HeadlessBackend())
        _default_registry.register(CdpBackend())
        _default_registry.register(MacChromeBackend())
    return _default_registry


def list_capture_backends() -> list[BackendInfo]:
    """List all registered backends and their availability."""
    return get_default_registry().list_backends()


__all__ = [
    "BackendInfo",
    "BackendRegistry",
    "CaptureBackend",
    "CdpBackend",
    "FileBackend",
    "HeadlessBackend",
    "MacChromeBackend",
    "get_default_registry",
    "list_capture_backends",
]
