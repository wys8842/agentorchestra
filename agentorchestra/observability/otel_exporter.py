"""OTel exporter 抽象（M5 横切骨架）。

完整实现在后续会话（roadmap §7）。本文件只提供：
- Exporter 抽象接口
- NoOpExporter 默认实现

后续会话接 OTel SDK 时新增 OTLPExporter 即可。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger("agentorchestra.observability.otel_exporter")


class OTelExporter(ABC):
    """OTel exporter 抽象。"""

    @abstractmethod
    def export(self, span: Dict[str, Any]) -> None:
        """导出一个 span。"""


class NoOpExporter(OTelExporter):
    """默认 NoOp 实现：丢弃所有 span，不发送。"""

    def export(self, span: Dict[str, Any]) -> None:
        return None


_default_exporter: Optional[OTelExporter] = None


def get_default_exporter() -> OTelExporter:
    """获取默认 exporter（懒加载）。"""
    global _default_exporter
    if _default_exporter is None:
        _default_exporter = NoOpExporter()
    return _default_exporter


def set_default_exporter(exporter: OTelExporter) -> None:
    """替换默认 exporter（测试或启动 OTLP 时用）。"""
    global _default_exporter
    _default_exporter = exporter
