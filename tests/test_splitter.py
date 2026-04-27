import pytest
from PIL import Image

from superweb2pdf.core.splitter import (
    SplitResult,
    find_blank_bands,
    find_split_points,
    is_blank_row,
    split_image,
)


def patterned_image(width: int, height: int) -> Image.Image:
    """Create an image whose rows are intentionally non-blank."""
    img = Image.new("RGB", (width, height), "white")
    for y in range(height):
        for x in range(width):
            img.putpixel((x, y), (0, 0, 0) if x % 2 == 0 else (255, 255, 255))
    return img


def paint_rows(img: Image.Image, start: int, end: int, color=(255, 255, 255)) -> None:
    for y in range(start, end + 1):
        for x in range(img.width):
            img.putpixel((x, y), color)


class TestIsBlankRow:
    def test_solid_color_row_is_blank(self):
        assert is_blank_row([(10, 20, 30)] * 8)

    def test_gradient_beyond_tolerance_is_not_blank(self):
        assert not is_blank_row([(0, 0, 0), (20, 0, 0), (40, 0, 0)], tolerance=5)

    def test_single_pixel_row_is_blank(self):
        assert is_blank_row([(123, 45, 67)])

    def test_empty_row_is_blank(self):
        assert is_blank_row([])

    def test_grayscale_rows_are_supported(self):
        assert is_blank_row([100, 102, 99], tolerance=3)
        assert not is_blank_row([0, 50, 100], tolerance=10)


class TestFindBlankBands:
    def test_simple_blank_regions(self):
        img = patterned_image(8, 20)
        paint_rows(img, 5, 9)
        paint_rows(img, 15, 19)

        assert find_blank_bands(img, min_band_height=3) == [(5, 9), (15, 19)]

    def test_no_blank_regions(self):
        img = patterned_image(8, 10)

        assert find_blank_bands(img, min_band_height=2) == []

    def test_entire_image_blank(self):
        img = Image.new("RGB", (8, 10), "white")

        assert find_blank_bands(img, min_band_height=1) == [(0, 9)]

    def test_single_row_bands(self):
        img = patterned_image(8, 5)
        paint_rows(img, 2, 2)

        assert find_blank_bands(img, min_band_height=1) == [(2, 2)]

    def test_bands_at_edges(self):
        img = patterned_image(8, 10)
        paint_rows(img, 0, 1)
        paint_rows(img, 8, 9)

        assert find_blank_bands(img, min_band_height=2) == [(0, 1), (8, 9)]


class TestFindSplitPoints:
    def test_image_shorter_than_max_height_has_no_splits(self):
        assert find_split_points(patterned_image(8, 50), max_page_height=100) == []

    def test_exact_multiple_of_max_height_uses_hard_cuts_without_blank_bands(self):
        img = patterned_image(8, 300)

        assert find_split_points(img, max_page_height=100) == [100, 200]

    def test_blank_band_near_ideal_cut_point_is_preferred(self):
        img = patterned_image(8, 220)
        paint_rows(img, 95, 105)

        assert find_split_points(img, max_page_height=100, min_blank_band=5) == [100, 200]

    def test_no_blank_bands_uses_hard_cuts(self):
        img = patterned_image(8, 250)

        assert find_split_points(img, max_page_height=100) == [100, 200]

    def test_multiple_pages_choose_multiple_split_points(self):
        img = patterned_image(8, 350)
        paint_rows(img, 95, 105)
        paint_rows(img, 200, 210)

        assert find_split_points(img, max_page_height=100, min_blank_band=5) == [100, 200, 300]

    def test_invalid_max_page_height_raises(self):
        with pytest.raises(ValueError, match="positive"):
            find_split_points(patterned_image(8, 10), max_page_height=0)


class TestSplitImage:
    def test_split_image_returns_valid_result(self):
        img = patterned_image(10, 250)
        result = split_image(img, max_page_height=100)

        assert isinstance(result, SplitResult)
        assert result.split_points == [100, 200]
        assert result.page_heights == [100, 100, 50]
        assert result.total_height == 250
        assert result.hard_cuts == [0, 1]

    def test_one_pixel_image_has_no_splits(self):
        result = split_image(Image.new("RGB", (1, 1), "white"), max_page_height=10)

        assert result.split_points == []
        assert result.page_heights == [1]
        assert result.hard_cuts == []

    def test_max_page_height_one_splits_every_row(self):
        img = patterned_image(2, 4)

        assert find_split_points(img, max_page_height=1, min_blank_band=1) == [1, 2, 3]

    def test_zero_tolerance_detects_only_exactly_uniform_rows(self):
        img = patterned_image(4, 8)
        paint_rows(img, 3, 4, (10, 10, 10))

        assert find_blank_bands(img, tolerance=0, min_band_height=1) == [(3, 4)]

    def test_huge_tolerance_does_not_duplicate_or_loop_on_blank_image(self):
        img = Image.new("RGB", (4, 250), "white")

        assert find_split_points(img, max_page_height=100, tolerance=255, min_blank_band=1) == [
            100,
            200,
        ]
