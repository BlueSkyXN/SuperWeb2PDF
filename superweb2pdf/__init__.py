# -*- coding: utf-8 -*-
"""SuperWeb2PDF — 将网页截图转为智能分页 PDF"""

__version__ = "0.1.0"
__author__ = "BlueSkyXN"

from superweb2pdf.core.splitter import find_blank_bands, find_split_points, split_image
from superweb2pdf.core.image_utils import load_image, stitch_vertical, resize_to_max_width, crop_pages
from superweb2pdf.core.pdf_builder import build_pdf, build_pdf_auto_size

__all__ = [
    "__version__",
    "__author__",
    "find_blank_bands",
    "find_split_points",
    "split_image",
    "load_image",
    "stitch_vertical",
    "resize_to_max_width",
    "crop_pages",
    "build_pdf",
    "build_pdf_auto_size",
]
