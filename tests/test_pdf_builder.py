"""Tests for the ReportLab PDF builder."""

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
    px_to_mm,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def assert_valid_pdf(path):
    assert path.exists()
    assert path.stat().st_size > 0
    assert path.read_bytes().startswith(b"%PDF")


def pdf_bytes(path_or_buffer):
    if isinstance(path_or_buffer, BytesIO):
        return path_or_buffer.getvalue()
    return path_or_buffer.read_bytes()


@pytest.fixture
def page_images():
    return [
        Image.new("RGB", (200, 400), "white"),
        Image.new("RGB", (200, 300), "lightblue"),
    ]


# ---------------------------------------------------------------------------
# Paper size parsing
# ---------------------------------------------------------------------------


class TestParsePaperSize:
    def test_named_sizes_are_case_insensitive(self):
        assert parse_paper_size("a4") == (210, 297)
        assert parse_paper_size("A4") == (210, 297)
        assert parse_paper_size("LETTER") == (215.9, 279.4)

    def test_custom_width_by_height(self):
        assert parse_paper_size("200x300") == (200.0, 300.0)
        assert parse_paper_size("200 × 300") == (200.0, 300.0)
        assert parse_paper_size("200.5 × 300.25") == (200.5, 300.25)

    @pytest.mark.parametrize("spec", ["", "unknown", "200", "200 by 300", "invalid"])
    def test_invalid_input_raises(self, spec):
        with pytest.raises(ValueError):
            parse_paper_size(spec)

    @pytest.mark.parametrize("spec", ["0x100", "100x0", "-1x100"])
    def test_non_positive_dimensions_raise(self, spec):
        with pytest.raises(ValueError):
            parse_paper_size(spec)


def test_paper_sizes_complete():
    assert {"a4", "a3", "letter", "legal", "b5", "tabloid"}.issubset(PAPER_SIZES)


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------


def test_unit_conversion_accuracy():
    assert mm_to_points(25.4) == pytest.approx(72.0, rel=1e-6)
    assert px_to_mm(150, 150) == pytest.approx(25.4)


def test_mm_to_points():
    assert mm_to_points(25.4) == pytest.approx(72.0, rel=1e-6)


# ---------------------------------------------------------------------------
# build_pdf — fixed paper size
# ---------------------------------------------------------------------------


class TestBuildPdf:
    def test_build_pdf_single_page(self, tmp_path):
        output = tmp_path / "single.pdf"

        result = build_pdf([Image.new("RGB", (100, 200), "white")], output)

        assert result == output
        assert_valid_pdf(output)

    def test_build_pdf_multiple_pages(self, tmp_path):
        output = tmp_path / "multi.pdf"
        pages = [
            Image.new("RGB", (100, 200), "white"),
            Image.new("RGB", (200, 100), "blue"),
        ]

        build_pdf(pages, output)

        assert_valid_pdf(output)

    def test_build_pdf_empty_list_raises(self, tmp_path):
        with pytest.raises(ValueError, match="empty"):
            build_pdf([], tmp_path / "empty.pdf")


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


# ---------------------------------------------------------------------------
# build_pdf_auto_size
# ---------------------------------------------------------------------------


class TestBuildPdfAutoSize:
    def test_build_pdf_auto_size_with_different_sized_pages(self, tmp_path):
        output = tmp_path / "auto.pdf"
        pages = [
            Image.new("RGB", (100, 200), "white"),
            Image.new("RGB", (300, 100), "blue"),
        ]

        result = build_pdf_auto_size(pages, output, dpi=100)

        assert result == output
        assert_valid_pdf(output)

    def test_build_pdf_auto_size_empty_list_raises(self, tmp_path):
        with pytest.raises(ValueError, match="empty"):
            build_pdf_auto_size([], tmp_path / "empty.pdf")


def test_build_pdf_auto_size(tmp_path):
    image = Image.new("RGB", (200, 400), "white")
    output = tmp_path / "auto.pdf"

    build_pdf_auto_size([image], output, dpi=150)

    data = output.read_bytes()
    assert data.startswith(b"%PDF")
    assert re.search(rb"/MediaBox\s*\[\s*0\s+0\s+96(?:\.0)?\s+192(?:\.0)?\s*\]", data)


# ---------------------------------------------------------------------------
# _fit_image_on_page
# ---------------------------------------------------------------------------


class TestFitImageOnPage:
    def test_wide_image_is_constrained_by_page_width(self):
        x, y, draw_w, draw_h = _fit_image_on_page(200, 100, 100, 100)

        assert x == pytest.approx(0)
        assert y == pytest.approx(25)
        assert draw_w == pytest.approx(100)
        assert draw_h == pytest.approx(50)

    def test_tall_image_is_constrained_by_page_height(self):
        x, y, draw_w, draw_h = _fit_image_on_page(100, 200, 100, 100)

        assert x == pytest.approx(25)
        assert y == pytest.approx(0)
        assert draw_w == pytest.approx(50)
        assert draw_h == pytest.approx(100)

    def test_matching_aspect_ratio_fills_page(self):
        assert _fit_image_on_page(100, 100, 50, 50) == pytest.approx((0, 0, 50, 50))

    @pytest.mark.parametrize("width,height", [(0, 10), (10, 0), (-1, 10)])
    def test_invalid_image_dimensions_raise(self, width, height):
        with pytest.raises(ValueError):
            _fit_image_on_page(width, height, 100, 100)


def test_fit_image_on_page_aspect_preserved():
    x, y, draw_w, draw_h = _fit_image_on_page(800, 400, 600, 600)

    assert x == pytest.approx(0)
    assert y == pytest.approx(150)
    assert draw_w <= 600
    assert draw_h <= 600
    assert draw_w / draw_h == pytest.approx(2.0)
