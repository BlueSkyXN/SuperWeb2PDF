"""文件输入捕获模块

从本地文件、glob 模式或目录加载图片，返回 PIL Image 供后续处理。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from superweb2pdf.core.image_utils import (
    IMAGE_EXTENSIONS,
    _natural_sort_key,
    glob_images,
    load_image,
    load_images,
    stitch_vertical,
)


def capture_from_file(path: str | Path) -> Image.Image:
    """Load a single image file and return it as an RGB PIL Image.

    Args:
        path: Path to the image file.

    Returns:
        An RGB-mode PIL Image.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file is not a valid image.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    try:
        return load_image(path)
    except Exception as exc:
        raise ValueError(
            f"Cannot open image file: {path}. "
            f"Supported formats: {', '.join(sorted(IMAGE_EXTENSIONS))}. "
            f"Original error: {exc}"
        ) from exc


def capture_from_files(pattern: str) -> Image.Image:
    """Load images matching a glob *pattern* and stitch them vertically.

    Args:
        pattern: A glob pattern (e.g. ``screenshots/*.png``).

    Returns:
        A single tall RGB PIL Image composed of all matched images.

    Raises:
        FileNotFoundError: If no files match the pattern.
    """
    paths = glob_images(pattern)

    if not paths:
        raise FileNotFoundError(
            f"No supported image files match pattern: {pattern}. "
            f"Supported formats: {', '.join(sorted(IMAGE_EXTENSIONS))}"
        )

    images = load_images(paths)
    return stitch_vertical(images)


def capture_from_directory(directory: str | Path) -> Image.Image:
    """Load all images in *directory*, sorted naturally, and stitch vertically.

    Args:
        directory: Path to a directory containing image files.

    Returns:
        A single tall RGB PIL Image composed of all images in the directory.

    Raises:
        NotADirectoryError: If *directory* is not an existing directory.
        FileNotFoundError: If the directory contains no image files.
    """
    directory = Path(directory)

    if not directory.exists():
        raise NotADirectoryError(f"Directory not found: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {directory}")

    image_paths = sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS),
        key=_natural_sort_key,
    )

    if not image_paths:
        raise FileNotFoundError(
            f"No supported image files found in directory: {directory}. "
            f"Supported formats: {', '.join(sorted(IMAGE_EXTENSIONS))}"
        )

    images = load_images(image_paths)
    return stitch_vertical(images)
