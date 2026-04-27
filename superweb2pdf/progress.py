"""Progress event types for SuperWeb2PDF conversions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

ProgressStage = Literal["capture", "preprocess", "split", "render", "write", "done"]


@dataclass(frozen=True)
class ProgressEvent:
    """A progress notification emitted during conversion."""

    stage: ProgressStage
    message: str
    percent: float | None = None
    current: int | None = None
    total: int | None = None


ProgressCallback = Callable[[ProgressEvent], None]

__all__ = [
    "ProgressStage",
    "ProgressEvent",
    "ProgressCallback",
]
