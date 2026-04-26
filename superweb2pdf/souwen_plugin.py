"""SouWen 插件声明 — 将 SuperWeb2PDF 注册为 SouWen fetch 数据源。

仅在 SouWen 已安装时生效。entry_point 声明在 pyproject.toml 中：
  [project.entry-points."souwen.plugins"]
  superweb2pdf = "superweb2pdf.souwen_plugin:plugin"

**重要**: 本模块 *不* 在顶层 import souwen —— 使用工厂函数延迟导入，
避免 entry_point 加载时的循环导入（souwen.registry.__init__ →
load_plugins → ep.load → import 本模块 → import souwen.registry → 循环）。
"""

from __future__ import annotations


def plugin():
    """工厂函数 — 被 SouWen plugin._coerce_to_adapters() 自动调用。"""
    from souwen.registry.adapter import MethodSpec, SourceAdapter
    from souwen.registry.loader import lazy

    adapter = SourceAdapter(
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

    # Auto-register fetch handler so `souwen fetch -p superweb2pdf` works
    try:
        from superweb2pdf.souwen_handler import register as _register_handler

        _register_handler()
    except Exception:
        pass  # handler registration is optional

    return adapter
