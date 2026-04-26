"""可选 fetch handler — 支持 `souwen fetch -p superweb2pdf` 命令行调用。"""
from __future__ import annotations

from typing import Any

from souwen.models import FetchResponse


async def superweb2pdf_fetch_handler(
    urls: list[str],
    timeout: float = 60.0,
    **kwargs: Any,
) -> FetchResponse:
    from superweb2pdf.souwen_client import SuperWeb2PdfClient

    async with SuperWeb2PdfClient() as client:
        return await client.fetch(urls, timeout=timeout, **kwargs)


def register() -> None:
    """注册 fetch handler 到 SouWen fetch 分发表。"""
    from souwen.web.fetch import register_fetch_handler

    register_fetch_handler("superweb2pdf", superweb2pdf_fetch_handler)
