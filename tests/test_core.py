"""Tests for core splitter and image utility modules."""

import pytest
from PIL import Image

from superweb2pdf.core.image_utils import (
    crop_pages,
    load_image,
    resize_to_max_width,
    stitch_vertical,
)
from superweb2pdf.core.splitter import find_blank_bands, split_image


@pytest.fixture
def sample_image():
    """Create a simple test image."""
    image = Image.new("RGB", (800, 2400), "lightblue")
    for y in range(image.height):
        image.putpixel((0, y), (0, 0, 128))
    return image


@pytest.fixture
def small_image():
    """Create a small test image (fits on one page)."""
    return Image.new("RGB", (800, 400), "white")


@pytest.fixture
def tmp_image(tmp_path, sample_image):
    """Save a sample image to a temp file."""
    path = tmp_path / "test.png"
    sample_image.save(str(path))
    return path


# Splitter

def test_split_image_simple(sample_image):
    result = split_image(sample_image, max_page_height=1000)

    assert result.total_height == 2400
    assert len(result.split_points) >= 2
    assert len(result.page_heights) == len(result.split_points) + 1
    assert sum(result.page_heights) == sample_image.height


def test_split_image_short(small_image):
    result = split_image(small_image, max_page_height=1000)

    assert result.split_points == []
    assert result.page_heights == [small_image.height]


def test_split_image_exact_height():
    image = Image.new("RGB", (800, 1000), "white")

    result = split_image(image, max_page_height=1000)

    assert result.split_points == []
    assert result.page_heights == [1000]


def test_find_blank_bands_all_white(small_image):
    bands = find_blank_bands(small_image, min_band_height=5)

    assert bands == [(0, small_image.height - 1)]


def test_find_blank_bands_no_blanks():
    image = Image.new("RGB", (20, 20), "white")
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))

    assert find_blank_bands(image, tolerance=0, min_band_height=2) == []


@pytest.mark.parametrize("max_height", [0, -1])
def test_split_image_invalid_height(small_image, max_height):
    with pytest.raises(ValueError):
        split_image(small_image, max_page_height=max_height)


# image_utils

def test_load_image(tmp_image):
    image = load_image(tmp_image)

    assert isinstance(image, Image.Image)
    assert image.mode == "RGB"
    assert image.size == (800, 2400)


def test_load_image_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_image(tmp_path / "missing.png")


def test_resize_to_max_width(sample_image):
    resized = resize_to_max_width(sample_image, max_width=400)

    assert resized.width == 400
    assert resized.height == 1200


def test_resize_to_max_width_smaller(small_image):
    resized = resize_to_max_width(small_image, max_width=1000)

    assert resized is small_image


def test_crop_pages_basic(sample_image):
    pages = crop_pages(sample_image, [1200])

    assert len(pages) == 2
    assert [page.size for page in pages] == [(800, 1200), (800, 1200)]


def test_crop_pages_empty_splits(small_image):
    pages = crop_pages(small_image, [])

    assert len(pages) == 1
    assert pages[0].size == small_image.size


def test_stitch_vertical():
    first = Image.new("RGB", (100, 50), "white")
    second = Image.new("RGB", (100, 75), "black")

    stitched = stitch_vertical([first, second])

    assert stitched.size == (100, 125)
    assert stitched.getpixel((0, 0)) == (255, 255, 255)
    assert stitched.getpixel((0, 124)) == (0, 0, 0)
