"""SouWen 插件声明 — 将 SuperWeb2PDF 注册为 SouWen fetch 数据源。

仅在 SouWen 已安装时生效。entry_point 声明在 pyproject.toml 中：
  [project.entry-points."souwen.plugins"]
  superweb2pdf = "superweb2pdf.souwen_plugin:plugin"
"""
from __future__ import annotations

from souwen.registry.adapter import MethodSpec, SourceAdapter
from souwen.registry.loader import lazy

plugin = SourceAdapter(
    name="superweb2pdf",
    domain="fetch",
    integration="self_hosted",
    description="SuperWeb2PDF — 网页全页截图智能分页转 PDF",
    config_field=None,
    client_loader=lazy("superweb2pdf.souwen_client:SuperWeb2PdfClient"),
    methods={"fetch": MethodSpec("fetch")},
    needs_config=False,
    default_enabled=True,
    tags=frozenset({"web2pdf", "external_plugin", "pdf"}),
)
