import pytest
from PIL import Image

from superweb2pdf.core.pdf_builder import (
    _fit_image_on_page,
    build_pdf,
    build_pdf_auto_size,
    mm_to_points,
    parse_paper_size,
    px_to_mm,
)


def assert_valid_pdf(path):
    assert path.exists()
    assert path.stat().st_size > 0
    assert path.read_bytes().startswith(b"%PDF")


class TestParsePaperSize:
    def test_named_sizes_are_case_insensitive(self):
        assert parse_paper_size("a4") == (210, 297)
        assert parse_paper_size("LETTER") == (215.9, 279.4)

    def test_custom_width_by_height(self):
        assert parse_paper_size("200x300") == (200.0, 300.0)
        assert parse_paper_size("200.5 × 300.25") == (200.5, 300.25)

    @pytest.mark.parametrize("spec", ["", "unknown", "200", "200 by 300"])
    def test_invalid_input_raises(self, spec):
        with pytest.raises(ValueError):
            parse_paper_size(spec)

    @pytest.mark.parametrize("spec", ["0x100", "100x0", "-1x100"])
    def test_non_positive_dimensions_raise(self, spec):
        with pytest.raises(ValueError):
            parse_paper_size(spec)


def test_unit_conversion_accuracy():
    assert mm_to_points(25.4) == pytest.approx(72.0, rel=1e-6)
    assert px_to_mm(150, 150) == pytest.approx(25.4)


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
