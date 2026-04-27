from pathlib import Path

import pytest
from PIL import Image

from superweb2pdf.capture.file_input import (
    capture_from_directory,
    capture_from_file,
    capture_from_files,
)


def save_image(path: Path, size=(10, 10), color="red", fmt=None) -> Path:
    Image.new("RGB", size, color).save(path, format=fmt)
    return path


class TestCaptureFromFile:
    def test_valid_image(self, tmp_path):
        path = save_image(tmp_path / "shot.png")

        img = capture_from_file(path)

        assert img.mode == "RGB"
        assert img.size == (10, 10)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            capture_from_file(tmp_path / "missing.png")

    def test_non_file_path_raises(self, tmp_path):
        with pytest.raises(ValueError, match="not a file"):
            capture_from_file(tmp_path)


class TestCaptureFromFiles:
    def test_glob_pattern_loads_and_stitches_naturally(self, tmp_path):
        save_image(tmp_path / "part10.png", size=(10, 10), color=(10, 0, 0))
        save_image(tmp_path / "part1.png", size=(10, 5), color=(1, 0, 0))
        save_image(tmp_path / "part2.png", size=(10, 7), color=(2, 0, 0))

        img = capture_from_files(str(tmp_path / "part*.png"))

        assert img.size == (10, 22)
        assert img.getpixel((0, 0))[0] == 1
        assert img.getpixel((0, 5))[0] == 2
        assert img.getpixel((0, 12))[0] == 10

    def test_no_matches_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            capture_from_files(str(tmp_path / "*.png"))


class TestCaptureFromDirectory:
    def test_valid_directory_loads_images(self, tmp_path):
        save_image(tmp_path / "img2.png", size=(10, 7), color=(2, 0, 0))
        save_image(tmp_path / "img1.png", size=(10, 5), color=(1, 0, 0))
        (tmp_path / "notes.txt").write_text("ignore")

        img = capture_from_directory(tmp_path)

        assert img.size == (10, 12)
        assert img.getpixel((0, 0))[0] == 1
        assert img.getpixel((0, 5))[0] == 2

    def test_empty_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            capture_from_directory(tmp_path)

    def test_non_directory_path_raises(self, tmp_path):
        path = tmp_path / "not-dir.txt"
        path.write_text("x")

        with pytest.raises(NotADirectoryError):
            capture_from_directory(path)
