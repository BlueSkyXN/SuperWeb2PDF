"""Tests for capture backend implementations and registry selection."""

from dataclasses import dataclass

import pytest
from PIL import Image

from superweb2pdf.backends import (
    BackendInfo,
    BackendRegistry,
    CdpBackend,
    FileBackend,
    HeadlessBackend,
    MacChromeBackend,
    get_default_registry,
    list_capture_backends,
)


@dataclass
class DummyBackend:
    name: str = "dummy"
    available: bool = True
    install_hint: str = "install dummy"

    def supports(self, source: str) -> bool:
        return source == "dummy://source"

    def capture(self, source: str, **kwargs) -> Image.Image:
        return Image.new("RGB", (1, 1), "white")


@pytest.fixture
def tmp_png(tmp_path):
    path = tmp_path / "test.png"
    Image.new("RGB", (8, 6), "red").save(path)
    return path


def test_file_backend_supports_existing_file(tmp_png):
    assert FileBackend().supports(str(tmp_png)) is True


def test_file_backend_not_supports_url():
    assert FileBackend().supports("https://example.com") is False


def test_file_backend_available():
    assert FileBackend().available is True


def test_file_backend_capture_file(tmp_png):
    image = FileBackend().capture(str(tmp_png))

    assert isinstance(image, Image.Image)
    assert image.size == (8, 6)
    assert image.mode == "RGB"


def test_headless_backend_supports_url():
    assert HeadlessBackend().supports("https://example.com") is True


def test_headless_backend_not_supports_file(tmp_png):
    assert HeadlessBackend().supports(str(tmp_png)) is False


def test_cdp_backend_supports_current():
    assert CdpBackend().supports("cdp://current") is True


def test_mac_chrome_supports_current_tab():
    assert MacChromeBackend().supports("current-tab") is True


def test_registry_register_and_get():
    registry = BackendRegistry()
    backend = DummyBackend()

    registry.register(backend)

    assert registry.get("dummy") is backend
    assert registry.get("DUMMY") is backend


def test_registry_get_unknown():
    assert BackendRegistry().get("missing") is None


def test_registry_list_backends():
    registry = BackendRegistry()
    registry.register(DummyBackend())

    backends = registry.list_backends()

    assert backends == [BackendInfo(name="dummy", available=True, install_hint="install dummy")]


def test_registry_auto_select_file(tmp_png):
    registry = BackendRegistry()
    registry.register(FileBackend())

    assert isinstance(registry.auto_select(str(tmp_png)), FileBackend)


def test_registry_auto_select_url(monkeypatch):
    monkeypatch.setattr(HeadlessBackend, "available", property(lambda self: True))
    registry = BackendRegistry()
    registry.register(FileBackend())
    registry.register(HeadlessBackend())
    registry.register(CdpBackend())

    selected = registry.auto_select("https://example.com")

    assert isinstance(selected, (HeadlessBackend, CdpBackend))


def test_default_registry():
    infos = get_default_registry().list_backends()

    assert len(infos) == 4
    assert {info.name for info in infos} == {"file", "headless", "cdp", "mac-chrome"}


def test_list_capture_backends():
    infos = list_capture_backends()

    assert infos
    assert all(isinstance(info, BackendInfo) for info in infos)
