"""Metrics 收集器抽象（M5 横切骨架）。

完整实现在后续会话（roadmap §7.3）。本文件只提供：
- MetricsCollector 抽象接口
- NoOpCollector 默认实现
- 关键 SLO 指标命名常量

指标语义：
- tx_rollback_rate: 事务回滚率（每分钟 rollback_count / commit_count）
- tx_duration_seconds: 事务平均耗时
- tx_compensation_triggered_total: 补偿触发次数
- agent_recall_hit_rate: Memory 召回命中率
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional

logger = logging.getLogger("agentorchestra.observability.metrics")


class MetricsCollector(ABC):
    """指标收集器抽象。"""

    @abstractmethod
    def increment(self, name: str, value: float = 1.0,
                  labels: Optional[Dict[str, str]] = None) -> None:
        """计数器 +1（可附加标签）。"""

    @abstractmethod
    def observe(self, name: str, value: float,
                labels: Optional[Dict[str, str]] = None) -> None:
        """记录一个观测值（如耗时）。"""

    @abstractmethod
    def gauge(self, name: str, value: float,
              labels: Optional[Dict[str, str]] = None) -> None:
        """设置 gauge 值。"""


class NoOpCollector(MetricsCollector):
    """默认 NoOp 实现：所有调用丢弃。"""

    def increment(self, name: str, value: float = 1.0,
                  labels: Optional[Dict[str, str]] = None) -> None:
        return None

    def observe(self, name: str, value: float,
                labels: Optional[Dict[str, str]] = None) -> None:
        return None

    def gauge(self, name: str, value: float,
              labels: Optional[Dict[str, str]] = None) -> None:
        return None


_default_collector: Optional[MetricsCollector] = None


def get_default_collector() -> MetricsCollector:
    """获取默认指标收集器（懒加载）。"""
    global _default_collector
    if _default_collector is None:
        _default_collector = NoOpCollector()
    return _default_collector


def set_default_collector(collector: MetricsCollector) -> None:
    """替换默认收集器。"""
    global _default_collector
    _default_collector = collector


# 关键 SLO 指标名常量（roadmap §7.2）
SLO_TX_ROLLBACK_RATE = "tx_rollback_rate"
SLO_TX_DURATION_SECONDS = "tx_duration_seconds"
SLO_TX_COMPENSATION_TRIGGERED = "tx_compensation_triggered_total"
SLO_AGENT_RECALL_HIT_RATE = "agent_recall_hit_rate"
