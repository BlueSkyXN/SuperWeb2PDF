"""SouWen 插件集成子包 — 将 SuperWeb2PDF 注册为 SouWen 的外部数据源。

仅在 SouWen (`pip install souwen`) 已安装时有实际效果。
entry_point 声明在 pyproject.toml:

    [project.entry-points."souwen.plugins"]
    superweb2pdf = "superweb2pdf.souwen.plugin:plugin"
"""

from __future__ import annotations

from superweb2pdf.souwen.plugin import plugin

__all__ = ["plugin"]
