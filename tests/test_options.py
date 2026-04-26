"""Tests for immutable SuperWeb2PDF option dataclasses."""

from dataclasses import FrozenInstanceError

import pytest

from superweb2pdf.errors import ConfigurationError
from superweb2pdf.options import CaptureOptions, PdfOptions, SplitOptions, WebToPdfOptions

# CaptureOptions

def test_default_capture_options():
    opts = CaptureOptions()

    assert opts.backend == "auto"
    assert opts.viewport_width == 1280
    assert opts.viewport_height == 900
    assert opts.scroll_delay_ms == 800
    assert opts.timeout_seconds == 60.0
    assert opts.retries == 0
    assert opts.cdp_port == 9222


def test_capture_options_invalid_backend():
    with pytest.raises(ConfigurationError):
        CaptureOptions(backend="invalid")  # type: ignore[arg-type]


@pytest.mark.parametrize("field", ["viewport_width", "viewport_height"])
@pytest.mark.parametrize("value", [0, -1])
def test_capture_options_invalid_viewport(field, value):
    with pytest.raises(ConfigurationError):
        CaptureOptions(**{field: value})


def test_capture_options_invalid_port():
    with pytest.raises(ConfigurationError):
        CaptureOptions(cdp_port=65536)


def test_capture_options_frozen():
    opts = CaptureOptions()

    with pytest.raises(FrozenInstanceError):
        opts.backend = "file"  # type: ignore[misc]


# SplitOptions

def test_default_split_options():
    opts = SplitOptions()

    assert opts.mode == "smart"
    assert opts.max_width is None
    assert opts.max_height is None
    assert opts.blank_threshold == 10
    assert opts.min_blank_band == 5
    assert opts.search_ratio == 0.2


def test_split_options_invalid_mode():
    with pytest.raises(ConfigurationError):
        SplitOptions(mode="invalid")  # type: ignore[arg-type]


def test_split_options_invalid_threshold():
    with pytest.raises(ConfigurationError):
        SplitOptions(blank_threshold=256)


def test_split_options_invalid_search_ratio():
    with pytest.raises(ConfigurationError):
        SplitOptions(search_ratio=1.01)


# PdfOptions

def test_default_pdf_options():
    opts = PdfOptions()

    assert opts.paper == "a4"
    assert opts.dpi == 150
    assert opts.auto_size is False
    assert opts.compression == "auto"
    assert opts.image_quality == 92
    assert opts.title is None
    assert opts.author is None
    assert opts.page_numbers is False
    assert opts.header_text is None
    assert opts.footer_text is None
    assert opts.watermark is None


def test_pdf_options_invalid_paper():
    with pytest.raises(ConfigurationError):
        PdfOptions(paper="invalid")


@pytest.mark.parametrize("dpi", [0, -1])
def test_pdf_options_invalid_dpi(dpi):
    with pytest.raises(ConfigurationError):
        PdfOptions(dpi=dpi)


def test_pdf_options_invalid_quality():
    with pytest.raises(ConfigurationError):
        PdfOptions(image_quality=101)


def test_pdf_options_custom_paper():
    opts = PdfOptions(paper="200x300")

    assert opts.paper == "200x300"


# WebToPdfOptions

def test_default_web_options():
    opts = WebToPdfOptions()

    assert isinstance(opts.capture, CaptureOptions)
    assert isinstance(opts.split, SplitOptions)
    assert isinstance(opts.pdf, PdfOptions)
    assert opts.capture.backend == "auto"
    assert opts.split.mode == "smart"
    assert opts.pdf.paper == "a4"


def test_simple_factory():
    opts = WebToPdfOptions.simple(paper="letter")

    assert opts.pdf.paper == "letter"
    assert opts.pdf.dpi == 150
    assert opts.split.mode == "smart"
    assert opts.capture.backend == "auto"


def test_to_dict_roundtrip():
    opts = WebToPdfOptions.simple(paper="letter", dpi=200, split="fixed", backend="file")

    assert WebToPdfOptions.from_dict(opts.to_dict()) == opts


def test_from_dict_partial():
    opts = WebToPdfOptions.from_dict({"pdf": {"paper": "legal"}, "split": {"mode": "none"}})

    assert opts.capture == CaptureOptions()
    assert opts.pdf.paper == "legal"
    assert opts.split.mode == "none"


def test_from_dict_invalid():
    with pytest.raises(ConfigurationError):
        WebToPdfOptions.from_dict("not a dict")  # type: ignore[arg-type]
