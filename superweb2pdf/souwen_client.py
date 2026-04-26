"""SouWen fetch 客户端 — 将 SuperWeb2PDF 的 sync API 包装为 async。"""
from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any

from souwen.models import FetchResponse, FetchResult

from superweb2pdf import WebToPdfOptions, convert_url


class SuperWeb2PdfClient:
    """Async SouWen client wrapping SuperWeb2PDF's convert_url()."""

    async def __aenter__(self) -> SuperWeb2PdfClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        pass

    async def fetch(
        self,
        urls: list[str],
        timeout: float = 60.0,
        **kwargs: Any,
    ) -> FetchResponse:
        results: list[FetchResult] = []
        for url in urls:
            result = await self._convert_one(url, timeout, **kwargs)
            results.append(result)

        ok = sum(1 for r in results if r.error is None)
        return FetchResponse(
            urls=urls,
            results=results,
            total=len(results),
            total_ok=ok,
            total_failed=len(results) - ok,
            provider="superweb2pdf",
        )

    async def _convert_one(
        self,
        url: str,
        timeout: float,
        **kwargs: Any,
    ) -> FetchResult:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._sync_convert, url, kwargs),
                timeout=timeout,
            )
            return result
        except asyncio.TimeoutError:
            return FetchResult(
                url=url,
                final_url=url,
                source="superweb2pdf",
                error=f"Timeout after {timeout}s",
            )
        except Exception as exc:
            return FetchResult(
                url=url,
                final_url=url,
                source="superweb2pdf",
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _sync_convert(url: str, kwargs: dict[str, Any]) -> FetchResult:
        buf = BytesIO()

        options = None
        if kwargs:
            try:
                options = WebToPdfOptions.from_dict(kwargs)
            except (TypeError, KeyError):
                options = None

        result = convert_url(url, output=buf, options=options)
        pdf_bytes = len(buf.getvalue())

        return FetchResult(
            url=url,
            final_url=url,
            source="superweb2pdf",
            title=f"SuperWeb2PDF: {url}",
            content=(
                f"# SuperWeb2PDF Capture\n\n"
                f"- URL: {url}\n"
                f"- Pages: {result.page_count}\n"
                f"- Backend: {result.backend}\n"
                f"- PDF size: {pdf_bytes:,} bytes\n"
            ),
            content_format="markdown",
            snippet=f"PDF with {result.page_count} pages ({pdf_bytes:,} bytes) via {result.backend}",
            raw={
                "page_count": result.page_count,
                "backend": result.backend,
                "file_size_bytes": pdf_bytes,
                "elapsed_seconds": result.elapsed_seconds,
                "source_type": result.source,
            },
        )
