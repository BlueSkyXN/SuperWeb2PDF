"""Domain exceptions for SuperWeb2PDF."""

from __future__ import annotations


class SuperWeb2PDFError(Exception):
    """Base exception for all SuperWeb2PDF errors."""


class CaptureError(SuperWeb2PDFError):
    """Error during page/image capture."""


class NavigationError(CaptureError):
    """Page navigation failed or timed out."""


class DependencyMissingError(SuperWeb2PDFError):
    """A required optional dependency is not installed."""

    def __init__(self, package: str, feature: str, install_hint: str):
        """Create an error describing a missing optional dependency."""
        self.package = package
        self.feature = feature
        self.install_hint = install_hint
        super().__init__(
            f"Optional dependency {package!r} is required for {feature}. "
            f"Install it with: {install_hint}"
        )


class SplitError(SuperWeb2PDFError):
    """Error during image splitting."""


class RenderError(SuperWeb2PDFError):
    """Error during PDF rendering."""


class ConfigurationError(SuperWeb2PDFError):
    """Invalid configuration or options."""


__all__ = [
    "SuperWeb2PDFError",
    "CaptureError",
    "NavigationError",
    "DependencyMissingError",
    "SplitError",
    "RenderError",
    "ConfigurationError",
]
