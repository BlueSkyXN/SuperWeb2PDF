"""Tests for the SuperWeb2PDF domain exception hierarchy."""

import pytest

from superweb2pdf.errors import (
    CaptureError,
    ConfigurationError,
    DependencyMissingError,
    NavigationError,
    RenderError,
    SplitError,
    SuperWeb2PDFError,
)


def test_error_hierarchy():
    assert issubclass(CaptureError, SuperWeb2PDFError)
    assert issubclass(NavigationError, SuperWeb2PDFError)
    assert issubclass(DependencyMissingError, SuperWeb2PDFError)
    assert issubclass(SplitError, SuperWeb2PDFError)
    assert issubclass(RenderError, SuperWeb2PDFError)
    assert issubclass(ConfigurationError, SuperWeb2PDFError)


def test_capture_error_is_superweb2pdf_error():
    assert isinstance(CaptureError("capture failed"), SuperWeb2PDFError)


def test_navigation_error_is_capture_error():
    assert isinstance(NavigationError("timeout"), CaptureError)


def test_dependency_missing_error_message():
    err = DependencyMissingError("playwright", "headless capture", "pip install playwright")

    message = str(err)
    assert "playwright" in message
    assert "headless capture" in message
    assert "pip install playwright" in message


def test_dependency_missing_error_attrs():
    err = DependencyMissingError("Quartz", "macOS capture", "pip install pyobjc-framework-Quartz")

    assert err.package == "Quartz"
    assert err.feature == "macOS capture"
    assert err.install_hint == "pip install pyobjc-framework-Quartz"


def test_split_error_is_superweb2pdf_error():
    assert isinstance(SplitError("split failed"), SuperWeb2PDFError)


def test_render_error_is_superweb2pdf_error():
    assert isinstance(RenderError("render failed"), SuperWeb2PDFError)


def test_configuration_error_is_superweb2pdf_error():
    assert isinstance(ConfigurationError("bad config"), SuperWeb2PDFError)


@pytest.mark.parametrize(
    "exc",
    [
        CaptureError("capture"),
        NavigationError("navigation"),
        DependencyMissingError("pkg", "feature", "install"),
        SplitError("split"),
        RenderError("render"),
        ConfigurationError("config"),
    ],
)
def test_catch_all_via_base_class(exc):
    with pytest.raises(SuperWeb2PDFError):
        raise exc
