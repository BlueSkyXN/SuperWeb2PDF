"""SuperWeb2PDF — 将网页截图转为智能分页 PDF"""

__version__ = "0.2.0"
__author__ = "BlueSkyXN"

from superweb2pdf.api import convert, convert_image, convert_pil, convert_url
from superweb2pdf.backends import list_capture_backends
from superweb2pdf.core.image_utils import (
    crop_pages,
    load_image,
    resize_to_max_width,
    stitch_vertical,
)
from superweb2pdf.core.pdf_builder import PdfOverlayOptions, build_pdf, build_pdf_auto_size
from superweb2pdf.core.splitter import find_blank_bands, find_split_points, split_image
from superweb2pdf.errors import CaptureError, ConfigurationError, RenderError, SuperWeb2PDFError
from superweb2pdf.options import CaptureOptions, PdfOptions, SplitOptions, WebToPdfOptions
from superweb2pdf.result import ConversionResult, PageInfo

__all__ = [
    "__version__",
    "__author__",
    # Low-level
    "find_blank_bands",
    "find_split_points",
    "split_image",
    "load_image",
    "stitch_vertical",
    "resize_to_max_width",
    "crop_pages",
    "build_pdf",
    "build_pdf_auto_size",
    "PdfOverlayOptions",
    # High-level API
    "convert",
    "convert_image",
    "convert_url",
    "convert_pil",
    "WebToPdfOptions",
    "CaptureOptions",
    "SplitOptions",
    "PdfOptions",
    "ConversionResult",
    "PageInfo",
    "SuperWeb2PDFError",
    "CaptureError",
    "RenderError",
    "ConfigurationError",
    "list_capture_backends",
]
