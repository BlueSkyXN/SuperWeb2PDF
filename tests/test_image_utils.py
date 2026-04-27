from pathlib import Path

import pytest
from PIL import Image

from superweb2pdf.core.image_utils import (
    crop_pages,
    glob_images,
    load_image,
    load_images,
    resize_to_max_width,
    stitch_vertical,
)


def save_image(path: Path, size=(10, 10), color="red", fmt=None) -> Path:
    Image.new("RGB", size, color).save(path, format=fmt)
    return path


class TestLoadImage:
    def test_load_valid_png_as_rgb(self, tmp_path):
        path = save_image(tmp_path / "sample.png", color="blue")

        img = load_image(path)

        assert img.mode == "RGB"
        assert img.size == (10, 10)

    def test_load_valid_jpeg_as_rgb(self, tmp_path):
        path = save_image(tmp_path / "sample.jpg", color="green", fmt="JPEG")

        img = load_image(path)

        assert img.mode == "RGB"
        assert img.size == (10, 10)

    def test_unsupported_format_raises(self, tmp_path):
        path = tmp_path / "sample.txt"
        path.write_text("not an image")

        with pytest.raises(ValueError, match="Unsupported image format"):
            load_image(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_image(tmp_path / "missing.png")

    def test_corrupt_file_raises(self, tmp_path):
        path = tmp_path / "corrupt.png"
        path.write_bytes(b"not a png")

        with pytest.raises(ValueError, match="Cannot (decode|identify)"):
            load_image(path)


def test_load_images_uses_natural_sort_order(tmp_path):
    p10 = save_image(tmp_path / "capture-10.png", color=(10, 0, 0))
    p1 = save_image(tmp_path / "capture-1.png", color=(1, 0, 0))
    p2 = save_image(tmp_path / "capture-2.png", color=(2, 0, 0))

    images = load_images([p10, p1, p2])

    assert [img.getpixel((0, 0))[0] for img in images] == [1, 2, 10]


class TestStitchVertical:
    def test_single_image_returns_copy(self):
        img = Image.new("RGB", (5, 7), "red")

        stitched = stitch_vertical([img])

        assert stitched.size == (5, 7)
        assert stitched is not img

    def test_multiple_same_width_images_are_stacked(self):
        images = [
            Image.new("RGB", (5, 3), "red"),
            Image.new("RGB", (5, 4), "blue"),
        ]

        stitched = stitch_vertical(images)

        assert stitched.size == (5, 7)
        assert stitched.getpixel((0, 0)) == (255, 0, 0)
        assert stitched.getpixel((0, 3)) == (0, 0, 255)

    def test_different_widths_are_scaled_to_first_width(self):
        first = Image.new("RGB", (10, 5), "red")
        second = Image.new("RGB", (20, 10), "blue")

        stitched = stitch_vertical([first, second])

        assert stitched.size == (10, 10)

    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="empty"):
            stitch_vertical([])


class TestResizeToMaxWidth:
    def test_image_already_fitting_is_returned_unchanged(self):
        img = Image.new("RGB", (10, 5), "red")

        assert resize_to_max_width(img, 20) is img

    def test_image_needing_resize_is_scaled_proportionally(self):
        img = Image.new("RGB", (100, 50), "red")

        resized = resize_to_max_width(img, 25)

        assert resized.size == (25, 12)

    def test_exact_width_is_returned_unchanged(self):
        img = Image.new("RGB", (10, 5), "red")

        assert resize_to_max_width(img, 10) is img


class TestCropPages:
    def test_no_split_points_returns_original_page(self):
        img = Image.new("RGB", (5, 10), "red")

        pages = crop_pages(img, [])

        assert [p.size for p in pages] == [(5, 10)]

    def test_single_split(self):
        img = Image.new("RGB", (5, 10), "red")

        pages = crop_pages(img, [4])

        assert [p.size for p in pages] == [(5, 4), (5, 6)]

    def test_multiple_splits_are_sorted(self):
        img = Image.new("RGB", (5, 10), "red")

        pages = crop_pages(img, [7, 3])

        assert [p.size for p in pages] == [(5, 3), (5, 4), (5, 3)]

    def test_split_at_boundaries_ignores_boundary_points(self):
        img = Image.new("RGB", (5, 10), "red")

        pages = crop_pages(img, [0, 10])

        assert [p.size for p in pages] == [(5, 10)]


class TestGlobImages:
    def test_matching_files_are_filtered_and_naturally_sorted(self, tmp_path):
        save_image(tmp_path / "img10.png")
        save_image(tmp_path / "img1.png")
        save_image(tmp_path / "img2.jpg", fmt="JPEG")
        (tmp_path / "notes.txt").write_text("ignore me")

        matches = glob_images(str(tmp_path / "img*"))

        assert [p.name for p in matches] == ["img1.png", "img2.jpg", "img10.png"]

    def test_no_matches_returns_empty_list(self, tmp_path):
        assert glob_images(str(tmp_path / "*.png")) == []

    def test_mixed_file_types_only_returns_supported_images(self, tmp_path):
        save_image(tmp_path / "a.png")
        save_image(tmp_path / "b.bmp", fmt="BMP")
        (tmp_path / "c.pdf").write_bytes(b"%PDF")

        assert [p.name for p in glob_images(str(tmp_path / "*"))] == ["a.png", "b.bmp"]
