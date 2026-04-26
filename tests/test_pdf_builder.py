"""Tests for the enhanced ReportLab PDF builder."""

import re
from io import BytesIO

import pytest
from PIL import Image

from superweb2pdf.core.pdf_builder import (
    PAPER_SIZES,
    PdfOverlayOptions,
    _fit_image_on_page,
    build_pdf,
    build_pdf_auto_size,
    mm_to_points,
    parse_paper_size,
)


@pytest.fixture
def page_images():
    return [Image.new("RGB", (200, 400), "white"), Image.new("RGB", (200, 300), "lightblue")]


def pdf_bytes(path_or_buffer):
    if isinstance(path_or_buffer, BytesIO):
        return path_or_buffer.getvalue()
    return path_or_buffer.read_bytes()


def test_build_pdf_basic(tmp_path, page_images):
    output = tmp_path / "out.pdf"

    result = build_pdf(page_images, output)

    assert result == output
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")


def test_build_pdf_bytesio(page_images):
    output = BytesIO()

    result = build_pdf(page_images, output)

    assert result is output
    assert output.getvalue().startswith(b"%PDF")


def test_build_pdf_auto_size(tmp_path):
    image = Image.new("RGB", (200, 400), "white")
    output = tmp_path / "auto.pdf"

    build_pdf_auto_size([image], output, dpi=150)

    data = output.read_bytes()
    assert data.startswith(b"%PDF")
    assert re.search(rb"/MediaBox\s*\[\s*0\s+0\s+96(?:\.0)?\s+192(?:\.0)?\s*\]", data)


def test_build_pdf_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        build_pdf([], tmp_path / "empty.pdf")


def test_build_pdf_generator(tmp_path, page_images):
    output = tmp_path / "generator.pdf"

    build_pdf((img for img in page_images), output)

    assert output.read_bytes().startswith(b"%PDF")


def test_build_pdf_with_overlay(tmp_path, page_images):
    output = tmp_path / "overlay.pdf"

    build_pdf(page_images, output, overlay=PdfOverlayOptions(page_numbers=True))

    assert output.stat().st_size > 0


def test_build_pdf_with_watermark(tmp_path, page_images):
    output = tmp_path / "watermark.pdf"

    build_pdf(page_images, output, overlay=PdfOverlayOptions(watermark="DRAFT"))

    assert output.stat().st_size > 0


def test_build_pdf_compression_jpeg(tmp_path, page_images):
    output = tmp_path / "jpeg.pdf"

    build_pdf(page_images, output, compression="jpeg")

    assert output.read_bytes().startswith(b"%PDF")


def test_build_pdf_metadata(tmp_path, page_images):
    output = tmp_path / "metadata.pdf"

    build_pdf(page_images, output, title="Test Title", author="Test Author")

    data = output.read_bytes()
    assert b"Test Title" in data
    assert b"Test Author" in data


def test_paper_sizes_complete():
    assert {"a4", "a3", "letter", "legal", "b5", "tabloid"}.issubset(PAPER_SIZES)


def test_parse_paper_size_named():
    assert parse_paper_size("a4") == (210, 297)
    assert parse_paper_size("A4") == (210, 297)


def test_parse_paper_size_custom():
    assert parse_paper_size("200x300") == (200.0, 300.0)
    assert parse_paper_size("200 × 300") == (200.0, 300.0)


def test_parse_paper_size_invalid():
    with pytest.raises(ValueError):
        parse_paper_size("invalid")


def test_mm_to_points():
    assert mm_to_points(25.4) == pytest.approx(72.0, rel=1e-6)


def test_fit_image_on_page():
    x, y, draw_w, draw_h = _fit_image_on_page(800, 400, 600, 600)

    assert x == pytest.approx(0)
    assert y == pytest.approx(150)
    assert draw_w <= 600
    assert draw_h <= 600
    assert draw_w / draw_h == pytest.approx(2.0)
