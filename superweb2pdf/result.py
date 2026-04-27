"""Result objects returned by SuperWeb2PDF conversions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PageInfo:
    """Information about one rendered PDF page."""

    index: int
    width_px: int
    height_px: int
    hard_cut: bool = False


@dataclass(frozen=True)
class WarningInfo:
    """Non-fatal warning emitted during conversion."""

    code: str
    message: str


@dataclass(frozen=True)
class ConversionResult:
    """Summary of a completed conversion."""

    output_path: Path | None
    page_count: int
    source: str
    backend: str
    pages: list[PageInfo]
    warnings: list[WarningInfo] = field(default_factory=list)
    file_size_bytes: int | None = None
    elapsed_seconds: float | None = None

    @property
    def ok(self) -> bool:
        """Return whether conversion succeeded."""
        return True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary representation."""
        data = asdict(self)
        data["output_path"] = str(self.output_path) if self.output_path is not None else None
        data["ok"] = self.ok
        return data


__all__ = [
    "PageInfo",
    "WarningInfo",
    "ConversionResult",
]
