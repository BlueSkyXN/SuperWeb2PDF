"""智能分页引擎 — SuperWeb2PDF 核心模块

分析全页网页截图，在空白/背景区域找到最优切割点，
避免文字和图片被截断。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _color_distance(c1: tuple[int, ...], c2: tuple[int, ...]) -> int:
    """Chebyshev (L∞) distance between two RGB/RGBA colours."""
    return max(abs(a - b) for a, b in zip(c1, c2))


def _row_pixels(image: Image.Image, y: int, step: int = 1) -> list[tuple[int, ...]]:
    """Return sampled pixel tuples for row *y*, taking every *step*-th pixel."""
    width = image.width
    return [image.getpixel((x, y)) for x in range(0, width, step)]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_blank_row(
    row_pixels: Sequence[tuple[int, ...] | int],
    tolerance: int = 10,
) -> bool:
    """Decide whether a row of pixel values is effectively a single solid colour.

    A row is considered *blank* when every sampled pixel is within *tolerance*
    (Chebyshev distance) of the row's **mode** colour – i.e. the most common
    pixel value.

    Parameters
    ----------
    row_pixels:
        Sequence of pixel values.  Each element is either an ``(R, G, B)`` /
        ``(R, G, B, A)`` tuple **or** a single int for greyscale images.
    tolerance:
        Maximum per-channel difference allowed from the mode colour.

    Returns
    -------
    bool
        ``True`` if the row is blank.
    """
    if not row_pixels:
        return True

    # Normalise scalars to 1-tuples so the rest of the logic is uniform.
    first = row_pixels[0]
    if isinstance(first, int):
        pixels: list[tuple[int, ...]] = [(p,) if isinstance(p, int) else p for p in row_pixels]
    else:
        pixels = list(row_pixels)  # type: ignore[arg-type]

    # Mode = most common colour.
    mode_color = Counter(pixels).most_common(1)[0][0]

    return all(_color_distance(px, mode_color) <= tolerance for px in pixels)


def find_blank_bands(
    image: Image.Image,
    tolerance: int = 10,
    min_band_height: int = 5,
) -> list[tuple[int, int]]:
    """Scan *image* row-by-row and return contiguous blank bands.

    For performance on wide images every 4th pixel is sampled per row.

    Parameters
    ----------
    image:
        A PIL ``Image`` (any mode accepted; internally converted to RGB).
    tolerance:
        Forwarded to :func:`is_blank_row`.
    min_band_height:
        Minimum number of consecutive blank rows to qualify as a band.

    Returns
    -------
    list[tuple[int, int]]
        Each tuple is ``(start_y, end_y)`` **inclusive** on both ends.
    """
    if image.mode != "RGB":
        image = image.convert("RGB")

    bands: list[tuple[int, int]] = []
    band_start: int | None = None
    sample_step = 4

    for y in range(image.height):
        pixels = _row_pixels(image, y, step=sample_step)
        if is_blank_row(pixels, tolerance=tolerance):
            if band_start is None:
                band_start = y
        else:
            if band_start is not None:
                band_height = y - band_start
                if band_height >= min_band_height:
                    bands.append((band_start, y - 1))
                band_start = None

    # Close any band that reaches the bottom edge.
    if band_start is not None:
        band_height = image.height - band_start
        if band_height >= min_band_height:
            bands.append((band_start, image.height - 1))

    return bands


def find_split_points(
    image: Image.Image,
    max_page_height: int,
    min_blank_band: int = 5,
    tolerance: int = 10,
    search_ratio: float = 0.2,
    _precomputed_bands: list[tuple[int, int]] | None = None,
) -> list[int]:
    """Find optimal y-coordinates at which to split a tall image into pages.

    Strategy
    --------
    1. Place *ideal* cut lines at multiples of *max_page_height*.
    2. Around each ideal position open a search window of
       ``±search_ratio * max_page_height``.
    3. Score every blank band inside the window by
       ``band_height × proximity_weight`` where *proximity_weight* falls
       linearly from 1.0 at the ideal position to 0.0 at the window edge.
    4. Pick the centre of the highest-scoring band.
    5. If no band is found → hard-cut at the ideal position.

    Parameters
    ----------
    image:
        The source screenshot.
    max_page_height:
        Target page height in pixels.
    min_blank_band:
        Minimum blank-band height forwarded to :func:`find_blank_bands`.
    tolerance:
        Forwarded to :func:`is_blank_row`.
    search_ratio:
        Fraction of *max_page_height* that defines the half-width of each
        search window.

    Returns
    -------
    list[int]
        Sorted y-coordinates of split lines (excluding ``0`` and
        ``image.height``).
    """
    if max_page_height <= 0:
        raise ValueError(f"max_page_height must be positive, got {max_page_height}")

    if image.mode != "RGB":
        image = image.convert("RGB")

    total_height = image.height
    if total_height <= max_page_height:
        return []

    # Pre-compute all blank bands once across the whole image.
    all_bands = (
        _precomputed_bands
        if _precomputed_bands is not None
        else find_blank_bands(
            image,
            tolerance=tolerance,
            min_band_height=min_blank_band,
        )
    )

    half_window = int(search_ratio * max_page_height)
    split_points: list[int] = []
    previous_cut = 0

    while True:
        ideal = previous_cut + max_page_height
        if ideal >= total_height:
            break

        win_lo = max(ideal - half_window, previous_cut + 1)
        win_hi = min(ideal + half_window, total_height - 1)

        # Collect candidate bands that overlap with the search window.
        candidates: list[tuple[float, int]] = []
        for band_start, band_end in all_bands:
            # Band must overlap the window.
            if band_end < win_lo or band_start > win_hi:
                continue

            band_height = band_end - band_start + 1
            band_centre = (band_start + band_end) // 2

            # Proximity weight: 1.0 at ideal, 0.0 at window edge.
            distance = abs(band_centre - ideal)
            proximity_weight = max(0.0, 1.0 - distance / half_window) if half_window > 0 else 1.0

            score = band_height * proximity_weight
            candidates.append((score, band_centre))

        if candidates:
            candidates.sort(key=lambda c: c[0], reverse=True)
            cut_y = candidates[0][1]
        else:
            cut_y = ideal  # hard cut

        split_points.append(cut_y)
        previous_cut = cut_y

    return split_points


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class SplitResult:
    """Outcome of :func:`split_image`."""

    split_points: list[int]
    """Y-coordinates where cuts are made."""

    page_heights: list[int]
    """Height (in pixels) of each resulting page."""

    total_height: int
    """Height of the original image."""

    hard_cuts: list[int] = field(default_factory=list)
    """Indices into *split_points* where no blank band was found (hard cuts)."""


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def split_image(
    image: Image.Image,
    max_page_height: int,
    **kwargs,
) -> SplitResult:
    """Compute split points for *image* and return a :class:`SplitResult`.

    All extra keyword arguments are forwarded to :func:`find_split_points`.
    """
    if image.mode != "RGB":
        image = image.convert("RGB")

    tolerance = kwargs.get("tolerance", 10)
    min_blank_band = kwargs.get("min_blank_band", 5)
    search_ratio = kwargs.get("search_ratio", 0.2)

    total_height = image.height

    # Compute blank bands once, reuse for both split finding and hard-cut detection.
    all_bands = find_blank_bands(
        image,
        tolerance=tolerance,
        min_band_height=min_blank_band,
    )

    split_points = find_split_points(
        image,
        max_page_height,
        min_blank_band=min_blank_band,
        tolerance=tolerance,
        search_ratio=search_ratio,
        _precomputed_bands=all_bands,
    )

    # Identify hard cuts by checking whether each split point sits inside
    # an already-computed blank band.
    hard_cuts: list[int] = []
    for idx, sp in enumerate(split_points):
        in_band = any(start <= sp <= end for start, end in all_bands)
        if not in_band:
            hard_cuts.append(idx)

    # Derive page heights from boundaries.
    boundaries = [0, *split_points, total_height]
    page_heights = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)]

    return SplitResult(
        split_points=split_points,
        page_heights=page_heights,
        total_height=total_height,
        hard_cuts=hard_cuts,
    )
