"""Tests for the high-level conversion API expected from superweb2pdf.api."""

import json
from io import BytesIO

import pytest
from PIL import Image

from superweb2pdf.api import convert, convert_image, convert_pil, convert_url
from superweb2pdf.options import PdfOptions, SplitOptions, WebToPdfOptions
from superweb2pdf.result import ConversionResult


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


def assert_successful_result(result: ConversionResult, expected_pages: int | None = None) -> None:
    assert isinstance(result, ConversionResult)
    assert result.ok is True
    assert result.page_count == len(result.pages)
    assert result.page_count > 0
    if expected_pages is not None:
        assert result.page_count == expected_pages


def test_convert_pil_image(sample_image):
    output = BytesIO()

    result = convert(sample_image, output)

    assert_successful_result(result)
    assert output.getvalue().startswith(b"%PDF")


def test_convert_pil_image_default_output(sample_image, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = convert(sample_image)

    assert_successful_result(result)
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path.suffix == ".pdf"


def test_convert_file_path(tmp_image, tmp_path):
    output = tmp_path / "out.pdf"

    result = convert(str(tmp_image), output)

    assert_successful_result(result)
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")


def test_convert_with_options(sample_image):
    output = BytesIO()
    options = WebToPdfOptions(
        split=SplitOptions(mode="none"),
        pdf=PdfOptions(paper="letter", dpi=100, auto_size=True),
    )

    result = convert(sample_image, output, options=options)

    assert_successful_result(result, expected_pages=1)


def test_convert_with_progress(sample_image):
    output = BytesIO()
    events = []

    result = convert(sample_image, output, progress=events.append)

    assert_successful_result(result)
    assert events
    assert events[-1].stage == "done"


def test_convert_result_ok(small_image):
    result = convert(small_image, BytesIO())

    assert result.ok is True


def test_convert_result_to_dict(small_image):
    result = convert(small_image, BytesIO())

    data = result.to_dict()

    assert data["ok"] is True
    assert data["page_count"] == result.page_count
    json.dumps(data)


def test_convert_image_shortcut(tmp_image, tmp_path):
    output = tmp_path / "shortcut.pdf"

    result = convert_image(tmp_image, output)

    assert_successful_result(result)
    assert output.exists()


def test_convert_pil_shortcut(small_image):
    output = BytesIO()

    result = convert_pil(small_image, output)

    assert_successful_result(result)
    assert output.getvalue().startswith(b"%PDF")


def test_convert_auto_size(small_image):
    options = WebToPdfOptions(pdf=PdfOptions(auto_size=True))

    result = convert(small_image, BytesIO(), options=options)

    assert_successful_result(result, expected_pages=1)


def test_convert_split_none(sample_image):
    options = WebToPdfOptions(split=SplitOptions(mode="none"))

    result = convert(sample_image, BytesIO(), options=options)

    assert_successful_result(result, expected_pages=1)


def test_convert_split_fixed(sample_image):
    options = WebToPdfOptions(split=SplitOptions(mode="fixed", max_height=1000))

    result = convert(sample_image, BytesIO(), options=options)

    assert_successful_result(result, expected_pages=3)
    assert [page.height_px for page in result.pages] == [1000, 1000, 400]


def test_convert_invalid_source(tmp_path):
    with pytest.raises(Exception):
        convert(tmp_path / "missing.png", BytesIO())


def test_convert_empty_image():
    image = Image.new("RGB", (0, 1))

    with pytest.raises(Exception):
        convert(image, BytesIO())


def test_convert_url(monkeypatch):
    captured = Image.new("RGB", (400, 400), "white")

    class FakeBackend:
        name = "fake-url"
        available = True
        install_hint = ""

        def supports(self, source: str) -> bool:
            return source.startswith("https://")

        def capture(self, source: str, **kwargs):
            return captured

    class FakeRegistry:
        def auto_select(self, source: str):
            return FakeBackend()

        def get(self, name: str):
            return FakeBackend()

    import superweb2pdf.api as api

    monkeypatch.setattr(api, "get_default_registry", lambda: FakeRegistry())

    result = convert_url("https://example.com", BytesIO())

    assert_successful_result(result, expected_pages=1)
    assert result.backend == "fake-url"
