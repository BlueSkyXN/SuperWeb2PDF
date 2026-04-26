"""Immutable configuration objects for SuperWeb2PDF conversions."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from superweb2pdf.errors import ConfigurationError

SplitMode = Literal["smart", "fixed", "none"]
CaptureBackendName = Literal["auto", "file", "headless", "cdp", "macos"]
CompressionMode = Literal["auto", "jpeg", "png"]

_CAPTURE_BACKENDS = {"auto", "file", "headless", "cdp", "macos"}
_SPLIT_MODES = {"smart", "fixed", "none"}
_COMPRESSION_MODES = {"auto", "jpeg", "png"}
_PAPER_SIZES = {"a4", "a3", "letter", "legal"}
_CUSTOM_PAPER_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)$")


def _ensure_bool(name: str, value: bool) -> None:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{name} must be a boolean")


def _ensure_positive_int(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")


def _ensure_non_negative_int(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigurationError(f"{name} must be a non-negative integer")


def _ensure_positive_number(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ConfigurationError(f"{name} must be a positive number")


def _validate_optional_string(name: str, value: str | None) -> None:
    if value is not None and not isinstance(value, str):
        raise ConfigurationError(f"{name} must be a string or None")


def _validate_paper(paper: str) -> None:
    if not isinstance(paper, str) or not paper.strip():
        raise ConfigurationError("paper must be a non-empty string")

    key = paper.strip().lower()
    if key in _PAPER_SIZES:
        return

    match = _CUSTOM_PAPER_RE.match(paper.strip())
    if not match:
        raise ConfigurationError(
            "paper must be one of a4, a3, letter, legal, or a custom WxH size in millimetres"
        )

    width_mm, height_mm = float(match.group(1)), float(match.group(2))
    if width_mm <= 0 or height_mm <= 0:
        raise ConfigurationError("custom paper dimensions must be positive")


@dataclass(frozen=True)
class CaptureOptions:
    """Options controlling page or image capture."""

    backend: CaptureBackendName = "auto"
    viewport_width: int = 1280
    viewport_height: int = 900
    scroll_delay_ms: int = 800
    timeout_seconds: float = 60.0
    retries: int = 0
    cdp_port: int = 9222

    def __post_init__(self) -> None:
        """Validate capture options."""
        if self.backend not in _CAPTURE_BACKENDS:
            raise ConfigurationError(f"backend must be one of {', '.join(sorted(_CAPTURE_BACKENDS))}")
        _ensure_positive_int("viewport_width", self.viewport_width)
        _ensure_positive_int("viewport_height", self.viewport_height)
        _ensure_non_negative_int("scroll_delay_ms", self.scroll_delay_ms)
        _ensure_positive_number("timeout_seconds", self.timeout_seconds)
        _ensure_non_negative_int("retries", self.retries)
        _ensure_positive_int("cdp_port", self.cdp_port)
        if self.cdp_port > 65535:
            raise ConfigurationError("cdp_port must be between 1 and 65535")


@dataclass(frozen=True)
class SplitOptions:
    """Options controlling screenshot pagination and splitting."""

    mode: SplitMode = "smart"
    max_width: int | None = None
    max_height: int | None = None
    blank_threshold: int = 10
    min_blank_band: int = 5
    search_ratio: float = 0.2

    def __post_init__(self) -> None:
        """Validate split options."""
        if self.mode not in _SPLIT_MODES:
            raise ConfigurationError(f"mode must be one of {', '.join(sorted(_SPLIT_MODES))}")
        if self.max_width is not None:
            _ensure_positive_int("max_width", self.max_width)
        if self.max_height is not None:
            _ensure_positive_int("max_height", self.max_height)
        _ensure_non_negative_int("blank_threshold", self.blank_threshold)
        if self.blank_threshold > 255:
            raise ConfigurationError("blank_threshold must be between 0 and 255")
        _ensure_positive_int("min_blank_band", self.min_blank_band)
        _ensure_positive_number("search_ratio", self.search_ratio)
        if self.search_ratio > 1:
            raise ConfigurationError("search_ratio must be between 0 and 1")


@dataclass(frozen=True)
class PdfOptions:
    """Options controlling PDF rendering and metadata."""

    paper: str = "a4"
    dpi: int = 150
    auto_size: bool = False
    compression: CompressionMode = "auto"
    image_quality: int = 92
    title: str | None = None
    author: str | None = None
    page_numbers: bool = False
    header_text: str | None = None
    footer_text: str | None = None
    watermark: str | None = None

    def __post_init__(self) -> None:
        """Validate PDF options."""
        _validate_paper(self.paper)
        _ensure_positive_int("dpi", self.dpi)
        _ensure_bool("auto_size", self.auto_size)
        if self.compression not in _COMPRESSION_MODES:
            raise ConfigurationError(
                f"compression must be one of {', '.join(sorted(_COMPRESSION_MODES))}"
            )
        _ensure_positive_int("image_quality", self.image_quality)
        if self.image_quality > 100:
            raise ConfigurationError("image_quality must be between 1 and 100")
        _validate_optional_string("title", self.title)
        _validate_optional_string("author", self.author)
        _ensure_bool("page_numbers", self.page_numbers)
        _validate_optional_string("header_text", self.header_text)
        _validate_optional_string("footer_text", self.footer_text)
        _validate_optional_string("watermark", self.watermark)


@dataclass(frozen=True)
class WebToPdfOptions:
    """Top-level options for a complete web-to-PDF conversion."""

    capture: CaptureOptions = field(default_factory=CaptureOptions)
    split: SplitOptions = field(default_factory=SplitOptions)
    pdf: PdfOptions = field(default_factory=PdfOptions)

    def __post_init__(self) -> None:
        """Validate nested option groups."""
        if not isinstance(self.capture, CaptureOptions):
            raise ConfigurationError("capture must be a CaptureOptions instance")
        if not isinstance(self.split, SplitOptions):
            raise ConfigurationError("split must be a SplitOptions instance")
        if not isinstance(self.pdf, PdfOptions):
            raise ConfigurationError("pdf must be a PdfOptions instance")

    @classmethod
    def simple(
        cls,
        *,
        paper: str = "a4",
        dpi: int = 150,
        split: SplitMode = "smart",
        backend: CaptureBackendName = "auto",
    ) -> "WebToPdfOptions":
        """Build common options from a few high-level settings."""
        return cls(
            capture=CaptureOptions(backend=backend),
            split=SplitOptions(mode=split),
            pdf=PdfOptions(paper=paper, dpi=dpi),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dictionary representation of these options."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WebToPdfOptions":
        """Create options from a dictionary with optional nested option groups."""
        if not isinstance(data, dict):
            raise ConfigurationError("data must be a dictionary")

        capture_data = data.get("capture", {})
        split_data = data.get("split", {})
        pdf_data = data.get("pdf", {})

        if not isinstance(capture_data, dict):
            raise ConfigurationError("capture must be a dictionary")
        if not isinstance(split_data, dict):
            raise ConfigurationError("split must be a dictionary")
        if not isinstance(pdf_data, dict):
            raise ConfigurationError("pdf must be a dictionary")

        return cls(
            capture=CaptureOptions(**capture_data),
            split=SplitOptions(**split_data),
            pdf=PdfOptions(**pdf_data),
        )


__all__ = [
    "SplitMode",
    "CaptureBackendName",
    "CompressionMode",
    "CaptureOptions",
    "SplitOptions",
    "PdfOptions",
    "WebToPdfOptions",
]
