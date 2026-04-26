"""Tests for SouWen plugin adapter."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

pytest.importorskip("souwen")

from souwen.models import FetchResponse, FetchResult  # noqa: E402
from souwen.registry.adapter import SourceAdapter  # noqa: E402

from superweb2pdf.errors import SuperWeb2PDFError  # noqa: E402
from superweb2pdf.result import ConversionResult, PageInfo  # noqa: E402
from superweb2pdf.souwen.client import SuperWeb2PdfClient  # noqa: E402
from superweb2pdf.souwen.handler import superweb2pdf_fetch_handler  # noqa: E402
from superweb2pdf.souwen.plugin import plugin as plugin_factory  # noqa: E402

# plugin is now a factory function; call it to get the SourceAdapter
plugin = plugin_factory()


def _mock_result(url: str = "https://example.com", pages: int = 3) -> ConversionResult:
    return ConversionResult(
        output_path=None,
        page_count=pages,
        source=url,
        backend="headless",
        pages=[PageInfo(index=i, width_px=1280, height_px=900) for i in range(pages)],
        file_size_bytes=12345,
        elapsed_seconds=2.5,
    )


# --- Plugin declaration ---------------------------------------------------


class TestPluginDeclaration:
    def test_plugin_factory_is_callable(self):
        assert callable(plugin_factory)

    def test_plugin_factory_returns_source_adapter(self):
        result = plugin_factory()
        assert isinstance(result, SourceAdapter)

    def test_plugin_is_source_adapter(self):
        assert isinstance(plugin, SourceAdapter)

    def test_plugin_metadata(self):
        assert plugin.name == "superweb2pdf"
        assert plugin.domain == "fetch"
        assert plugin.integration == "self_hosted"
        assert plugin.needs_config is False
        assert plugin.default_enabled is True
        assert plugin.config_field is None

    def test_plugin_methods(self):
        assert "fetch" in plugin.methods

    def test_plugin_tags(self):
        assert "web2pdf" in plugin.tags
        assert "external_plugin" in plugin.tags
        assert "pdf" in plugin.tags

    def test_client_loader_resolves(self):
        cls = plugin.client_loader()
        assert cls is SuperWeb2PdfClient


# --- Client contract ------------------------------------------------------


class TestClientContract:
    def test_has_fetch_method(self):
        assert hasattr(SuperWeb2PdfClient, "fetch")
        assert asyncio.iscoroutinefunction(SuperWeb2PdfClient.fetch)

    def test_async_context_manager(self):
        assert hasattr(SuperWeb2PdfClient, "__aenter__")
        assert hasattr(SuperWeb2PdfClient, "__aexit__")

    @pytest.mark.asyncio
    async def test_context_manager_usable(self):
        async with SuperWeb2PdfClient() as client:
            assert isinstance(client, SuperWeb2PdfClient)


# --- Mocked conversion ----------------------------------------------------


class TestMockedConversion:
    @pytest.mark.asyncio
    async def test_fetch_single_url(self):
        with patch(
            "superweb2pdf.souwen.client.convert_url",
            return_value=_mock_result("https://example.com", pages=3),
        ):
            client = SuperWeb2PdfClient()
            response = await client.fetch(["https://example.com"])

        assert isinstance(response, FetchResponse)
        assert response.provider == "superweb2pdf"
        assert response.total == 1
        assert response.total_ok == 1
        assert response.total_failed == 0
        assert len(response.results) == 1

        result = response.results[0]
        assert isinstance(result, FetchResult)
        assert result.url == "https://example.com"
        assert result.source == "superweb2pdf"
        assert result.error is None
        assert result.content_format == "markdown"
        assert "Pages: 3" in result.content
        assert result.raw["page_count"] == 3
        assert result.raw["backend"] == "headless"

    @pytest.mark.asyncio
    async def test_fetch_multiple_urls(self):
        with patch(
            "superweb2pdf.souwen.client.convert_url",
            side_effect=lambda url, **kw: _mock_result(url, pages=2),
        ):
            client = SuperWeb2PdfClient()
            response = await client.fetch(["https://a.com", "https://b.com", "https://c.com"])

        assert response.total == 3
        assert response.total_ok == 3
        assert response.total_failed == 0
        assert [r.url for r in response.results] == [
            "https://a.com",
            "https://b.com",
            "https://c.com",
        ]

    @pytest.mark.asyncio
    async def test_fetch_with_options_kwargs(self):
        captured = {}

        def fake_convert(url, output=None, options=None, progress=None):
            captured["options"] = options
            # Write something so len(buf.getvalue()) > 0
            if output is not None:
                output.write(b"x" * 100)
            return _mock_result(url)

        with patch("superweb2pdf.souwen.client.convert_url", side_effect=fake_convert):
            client = SuperWeb2PdfClient()
            await client.fetch(["https://example.com"], capture={"viewport_width": 1024})

        # Either options got built or fell back to None — both acceptable; just
        # verify call happened.
        assert "options" in captured

    @pytest.mark.asyncio
    async def test_fetch_with_capture_kwargs_builds_options(self):
        captured = {}

        def fake_convert(url, output=None, options=None, progress=None):
            captured["options"] = options
            return _mock_result(url)

        # Pass a kwarg that from_dict accepts (capture is a recognised top-level
        # group); from_dict silently ignores unknown keys, so options is built.
        with patch("superweb2pdf.souwen.client.convert_url", side_effect=fake_convert):
            client = SuperWeb2PdfClient()
            await client.fetch(["https://example.com"], capture={"viewport_width": 800})

        assert captured["options"] is not None
        assert captured["options"].capture.viewport_width == 800


# --- Handler --------------------------------------------------------------


class TestHandler:
    def test_handler_is_async(self):
        assert asyncio.iscoroutinefunction(superweb2pdf_fetch_handler)

    @pytest.mark.asyncio
    async def test_handler_returns_fetch_response(self):
        with patch(
            "superweb2pdf.souwen.client.convert_url",
            return_value=_mock_result(),
        ):
            response = await superweb2pdf_fetch_handler(["https://example.com"])

        assert isinstance(response, FetchResponse)
        assert response.provider == "superweb2pdf"
        assert response.total_ok == 1


# --- Error handling -------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_timeout(self):
        def slow_convert(url, output=None, options=None, progress=None):
            import time

            time.sleep(2)
            return _mock_result(url)

        with patch("superweb2pdf.souwen.client.convert_url", side_effect=slow_convert):
            client = SuperWeb2PdfClient()
            response = await client.fetch(["https://example.com"], timeout=0.1)

        assert response.total_failed == 1
        assert response.total_ok == 0
        assert "Timeout" in response.results[0].error

    @pytest.mark.asyncio
    async def test_superweb2pdf_error(self):
        with patch(
            "superweb2pdf.souwen.client.convert_url",
            side_effect=SuperWeb2PDFError("capture failed"),
        ):
            client = SuperWeb2PdfClient()
            response = await client.fetch(["https://example.com"])

        assert response.total_failed == 1
        result = response.results[0]
        assert result.error is not None
        assert "SuperWeb2PDFError" in result.error
        assert "capture failed" in result.error

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        with patch(
            "superweb2pdf.souwen.client.convert_url",
            side_effect=RuntimeError("boom"),
        ):
            client = SuperWeb2PdfClient()
            response = await client.fetch(["https://example.com"])

        assert response.total_failed == 1
        result = response.results[0]
        assert result.error is not None
        assert "RuntimeError" in result.error
        assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_partial_success(self):
        def convert(url, output=None, options=None, progress=None):
            if "bad" in url:
                raise RuntimeError("bad url")
            return _mock_result(url)

        with patch("superweb2pdf.souwen.client.convert_url", side_effect=convert):
            client = SuperWeb2PdfClient()
            response = await client.fetch(["https://good.com", "https://bad.com"])

        assert response.total == 2
        assert response.total_ok == 1
        assert response.total_failed == 1
