"""Tests for progress event dataclasses and type aliases."""

from dataclasses import FrozenInstanceError
from typing import get_args

import pytest

from superweb2pdf.progress import ProgressCallback, ProgressEvent, ProgressStage


def test_progress_event_creation():
    event = ProgressEvent(
        stage="capture",
        message="Capturing page",
        percent=25.0,
        current=1,
        total=4,
    )

    assert event.stage == "capture"
    assert event.message == "Capturing page"
    assert event.percent == 25.0
    assert event.current == 1
    assert event.total == 4


def test_progress_event_frozen():
    event = ProgressEvent(stage="done", message="Finished")

    with pytest.raises(FrozenInstanceError):
        event.message = "changed"  # type: ignore[misc]


def test_progress_event_defaults():
    event = ProgressEvent(stage="render", message="Rendering")

    assert event.percent is None
    assert event.current is None
    assert event.total is None


def test_progress_callback_type():
    events = []

    def callback(event: ProgressEvent) -> None:
        events.append(event)

    callback(ProgressEvent(stage="write", message="Writing"))

    assert callable(callback)
    assert ProgressCallback is not None
    assert len(events) == 1


def test_progress_stages():
    assert set(get_args(ProgressStage)) == {
        "capture",
        "preprocess",
        "split",
        "render",
        "write",
        "done",
    }
