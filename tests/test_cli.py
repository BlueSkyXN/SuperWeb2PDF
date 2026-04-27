import argparse

import pytest

from superweb2pdf.cli import auto_output_name, parse_args


def test_parse_args_image_source():
    args = parse_args(["--image", "shot.png"])

    assert args.image == "shot.png"
    assert args.dpi == 150
    assert args.paper == "a4"
    assert args.split == "smart"


def test_parse_args_images_source(tmp_path):
    from PIL import Image

    Image.new("RGB", (1, 1), "white").save(tmp_path / "shot-1.png")

    args = parse_args(["--images", str(tmp_path / "*.png")])

    assert args.images == str(tmp_path / "*.png")


def test_parse_args_url_source():
    args = parse_args(["--url", "https://example.com"])

    assert args.url == "https://example.com"


def test_parse_args_current_tab_source():
    args = parse_args(["--current-tab"])

    assert args.current_tab is True


def test_parse_args_watch_source():
    args = parse_args(["--watch", "incoming"])

    assert args.watch == "incoming"


def test_capture_options_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        parse_args(["--image", "a.png", "--url", "https://example.com"])


def test_defaults():
    args = parse_args(["--image", "shot.png"])

    assert args.dpi == 150
    assert args.paper == "a4"
    assert args.split == "smart"
    assert args.blank_threshold == 10
    assert args.min_blank_band == 5


@pytest.mark.parametrize(
    "argv",
    [
        ["--image", "a.png", "--max-width", "0"],
        ["--image", "a.png", "--max-height", "-1"],
        ["--image", "a.png", "--dpi", "0"],
        ["--image", "a.png", "--min-blank-band", "0"],
        ["--image", "a.png", "--blank-threshold", "-1"],
        ["--image", "a.png", "--scroll-delay", "-1"],
        ["--image", "a.png", "--cdp", "0"],
    ],
)
def test_numeric_argument_validation(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)


class TestAutoOutputName:
    def test_image_input_uses_same_stem(self):
        args = argparse.Namespace(image="screens/page.png", images=None, current_tab=False, url=None)

        assert auto_output_name(args) == "screens/page.pdf"

    def test_images_pattern_replaces_wildcard_in_stem(self):
        args = argparse.Namespace(image=None, images="screens/page-*.png", current_tab=False, url=None)

        assert auto_output_name(args) == "screens/page-output.pdf"

    def test_url_input_includes_hostname(self):
        args = argparse.Namespace(image=None, images=None, current_tab=False, url="https://example.com/path")

        output = auto_output_name(args)
        assert output.startswith("superweb2pdf-example.com-")
        assert output.endswith(".pdf")

    def test_current_tab_input_uses_capture_prefix(self):
        args = argparse.Namespace(image=None, images=None, current_tab=True, url=None)

        output = auto_output_name(args)
        assert output.startswith("capture-")
        assert output.endswith(".pdf")

    def test_no_input_falls_back_to_output_pdf(self):
        args = argparse.Namespace(image=None, images=None, current_tab=False, url=None)

        assert auto_output_name(args) == "output.pdf"


def test_cdp_alone_is_allowed_and_marks_current_page_mode():
    args = parse_args(["--cdp", "9222"])

    assert args.cdp == 9222
    assert args._cdp_current_page is True


def test_cdp_with_url_does_not_mark_current_page_mode():
    args = parse_args(["--url", "https://example.com", "--cdp", "9222"])

    assert args._cdp_current_page is False


def test_no_input_is_an_error():
    with pytest.raises(SystemExit):
        parse_args([])


def test_invalid_split_choice_is_an_error():
    with pytest.raises(SystemExit):
        parse_args(["--image", "a.png", "--split", "invalid"])
