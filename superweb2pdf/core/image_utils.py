"""图片加载、拼接与处理工具

提供截图加载、纵向拼接、缩放、分页裁切、glob 自然排序等功能。
"""

from __future__ import annotations

import glob as globlib
import re
from pathlib import Path
from typing import Sequence

from PIL import Image, UnidentifiedImageError

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp"})

_NUM_RE = re.compile(r"(\d+)")


def _natural_sort_key(path: Path) -> list[int | str]:
    """Return a sort key that orders numbers numerically within filenames."""
    parts: list[int | str] = []
    for tok in _NUM_RE.split(path.name):
        parts.append(int(tok) if tok.isdigit() else tok.lower())
    return parts


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_image(path: str | Path) -> Image.Image:
    """Load a single image file and convert it to RGB mode.

    Args:
        path: Filesystem path to an image (PNG, JPEG, WebP, TIFF, BMP).

    Returns:
        A PIL Image in RGB mode.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file extension is unsupported or Pillow cannot
            identify the image format.
        OSError: If Pillow identifies the file but cannot decode/read it.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Image file not found: {p}")
    if not p.is_file():
        raise ValueError(f"Image path is not a file: {p}")
    if p.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported image format '{p.suffix}' for file: {p}. "
            f"Supported formats: {', '.join(sorted(IMAGE_EXTENSIONS))}"
        )
    try:
        with Image.open(p) as img:
            img.load()  # force decode to catch corrupt files early
            return img.convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError(f"Cannot decode or identify image file: {p}") from exc
    except OSError as exc:
        raise OSError(f"Cannot decode image file: {p}") from exc


def load_images(paths: Sequence[str | Path]) -> list[Image.Image]:
    """Load multiple images, all converted to RGB.

    Paths whose filenames contain numeric segments are sorted naturally
    (e.g. ``capture-2.png`` before ``capture-10.png``).

    Args:
        paths: List of filesystem paths to image files.

    Returns:
        List of PIL Images in RGB mode, sorted naturally by filename.
    """
    sorted_paths = sorted((Path(p) for p in paths), key=_natural_sort_key)
    return [load_image(p) for p in sorted_paths]


# ---------------------------------------------------------------------------
# Stitching / resizing
# ---------------------------------------------------------------------------


def stitch_vertical(images: list[Image.Image]) -> Image.Image:
    """Stitch images vertically into one tall image.

    Every image is scaled to match the width of the *first* image while
    maintaining its aspect ratio.

    Args:
        images: Non-empty list of PIL Images.

    Returns:
        A single PIL Image containing all inputs stacked top-to-bottom.

    Raises:
        ValueError: If *images* is empty.
    """
    if not images:
        raise ValueError("Cannot stitch an empty list of images.")
    for idx, img in enumerate(images):
        if img.width <= 0 or img.height <= 0:
            raise ValueError(f"Invalid image dimensions at index {idx}: {img.width}×{img.height}")

    if len(images) == 1:
        return images[0].convert("RGB") if images[0].mode != "RGB" else images[0].copy()

    target_width = images[0].width
    scaled_sizes: list[tuple[int, int]] = []
    for img in images:
        if img.width != target_width:
            ratio = target_width / img.width
            new_height = max(1, round(img.height * ratio))
            scaled_sizes.append((target_width, new_height))
        else:
            scaled_sizes.append((target_width, img.height))

    total_height = sum(height for _, height in scaled_sizes)
    if total_height <= 0:
        raise ValueError("Stitched image would have non-positive height")

    result = Image.new("RGB", (target_width, total_height))
    y_offset = 0
    for img, size in zip(images, scaled_sizes):
        if img.size != size:
            paste_img = img.resize(size, Image.LANCZOS)
        else:
            paste_img = img

        if paste_img.mode != "RGB":
            paste_img = paste_img.convert("RGB")

        result.paste(paste_img, (0, y_offset))
        y_offset += paste_img.height
    return result


def resize_to_max_width(image: Image.Image, max_width: int) -> Image.Image:
    """Scale *image* down if it exceeds *max_width*, preserving aspect ratio.

    Uses LANCZOS resampling for quality.  If the image already fits within
    *max_width*, it is returned unchanged (no copy).

    Args:
        image: Source PIL Image.
        max_width: Maximum allowed pixel width.

    Returns:
        The (possibly resized) PIL Image.
    """
    if max_width <= 0:
        raise ValueError(f"max_width must be positive, got {max_width}")
    if image.width <= 0 or image.height <= 0:
        raise ValueError(f"Invalid image dimensions: {image.width}×{image.height}")

    if image.width <= max_width:
        return image
    ratio = max_width / image.width
    new_height = max(1, round(image.height * ratio))
    return image.resize((max_width, new_height), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Cropping
# ---------------------------------------------------------------------------


def crop_pages(
    image: Image.Image,
    split_points: Sequence[int],
) -> list[Image.Image]:
    """Crop a tall image into page-sized pieces at the given y-coordinates.

    ``split_points`` should **not** include ``0`` or ``image.height``; those
    boundaries are implicit.

    Example::

        crop_pages(img, [1000, 2000])
        # height=3000 → pages [0:1000], [1000:2000], [2000:3000]

    Args:
        image: The source (tall) PIL Image.
        split_points: Sorted list of y-coordinates where cuts are made.

    Returns:
        List of cropped PIL Images, one per page.
    """
    if image.width <= 0 or image.height <= 0:
        raise ValueError(f"Invalid image dimensions: {image.width}×{image.height}")

    normalised_points: set[int] = set()
    for point in split_points:
        if not isinstance(point, int):
            raise TypeError(f"Split point must be an integer, got {type(point).__name__}")
        if point < 0 or point > image.height:
            raise ValueError(f"Split point {point} is outside image bounds 0..{image.height}")
        # Boundary cuts are harmless inputs but must not produce empty pages.
        if point in (0, image.height):
            continue
        normalised_points.add(point)

    boundaries = [0, *sorted(normalised_points), image.height]
    pages: list[Image.Image] = []
    for top, bottom in zip(boundaries, boundaries[1:]):
        if bottom > top:
            pages.append(image.crop((0, top, image.width, bottom)))
    return pages


# ---------------------------------------------------------------------------
# Globbing
# ---------------------------------------------------------------------------


def glob_images(pattern: str) -> list[Path]:
    """Expand *pattern* and return naturally-sorted image file paths.

    Only files whose extension matches a supported image format are included.

    Args:
        pattern: A filesystem glob pattern (e.g. ``screenshots/*.png``).

    Returns:
        Naturally sorted list of :class:`~pathlib.Path` objects.
    """
    expanded_pattern = str(Path(pattern).expanduser())
    matched = (Path(p) for p in globlib.glob(expanded_pattern, recursive=True))
    images = [p for p in matched if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return sorted(images, key=_natural_sort_key)
