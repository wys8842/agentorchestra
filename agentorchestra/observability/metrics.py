"""Metrics 收集器抽象 + PrometheusTextCollector（M5 横切，零依赖）。

提供：
- MetricsCollector 抽象接口（increment/observe/gauge）
- NoOpCollector 默认实现（未启用时零影响）
- PrometheusTextCollector：内存 metric + render() 输出 Prometheus 文本
  （基于 observability/prometheus.py 渲染器，无 prometheus_client 依赖）
- SLO 指标命名常量

设计见 docs/superpowers/specs/2026-09-04-m5-observability-design.md §4.2
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from threading import RLock
from typing import Dict, Optional

from .prometheus import Counter, Gauge, Histogram

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
        """记录一个观测值（如耗时，进 histogram）。"""

    @abstractmethod
    def gauge(self, name: str, value: float,
              labels: Optional[Dict[str, str]] = None) -> None:
        """设置 gauge 值。"""

    def render(self) -> str:
        """渲染为 Prometheus 文本（默认空）。"""
        return ""


class NoOpCollector(MetricsCollector):
    """默认 NoOp 实现：所有调用丢弃。"""

    def increment(self, name: str, value: float = 1.0,
                  labels: Optional[Dict[str, str]] = None) -> None:
        """NoOp：丢弃。"""

    def observe(self, name: str, value: float,
                labels: Optional[Dict[str, str]] = None) -> None:
        """NoOp：丢弃。"""

    def gauge(self, name: str, value: float,
              labels: Optional[Dict[str, str]] = None) -> None:
        """NoOp：丢弃。"""


class PrometheusTextCollector(MetricsCollector):
    """纯内存指标收集器，render() 生成 Prometheus 文本（零依赖）。

    用法：
        c = PrometheusTextCollector()
        c.increment("tx_rollback_total", 1, {"reason": "abort"})
        c.observe("tx_duration_seconds", 1.2, {"result": "committed"})
        text = c.render()  # Prometheus text exposition
    """

    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]

    def __init__(self):
        self._lock = RLock()
        self._counters: Dict[str, Counter] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._helps: Dict[str, str] = {}

    def _counter(self, name: str) -> Counter:
        with self._lock:
            c = self._counters.get(name)
            if c is None:
                c = Counter(name, self._helps.get(name, name))
                self._counters[name] = c
            return c

    def _histogram(self, name: str) -> Histogram:
        with self._lock:
            h = self._histograms.get(name)
            if h is None:
                h = Histogram(name, self._helps.get(name, name),
                              self.DEFAULT_BUCKETS)
                self._histograms[name] = h
            return h

    def _gauge(self, name: str) -> Gauge:
        with self._lock:
            g = self._gauges.get(name)
            if g is None:
                g = Gauge(name, self._helps.get(name, name))
                self._gauges[name] = g
            return g

    def describe(self, name: str, help_text: str) -> None:
        """注册指标说明。"""
        self._helps[name] = help_text

    # ---------------- 接口 ----------------

    def increment(self, name: str, value: float = 1.0,
                  labels: Optional[Dict[str, str]] = None) -> None:
        """计数器累加。"""
        self._counter(name).inc(value, labels)

    def observe(self, name: str, value: float,
                labels: Optional[Dict[str, str]] = None) -> None:
        """记录观测值到直方图。"""
        self._histogram(name).observe(value, labels)

    def gauge(self, name: str, value: float,
              labels: Optional[Dict[str, str]] = None) -> None:
        """设置 gauge 值。"""
        self._gauge(name).set(value, labels)

    def render(self) -> str:
        """输出 Prometheus 文本格式。"""
        with self._lock:
            parts = []
            for c in self._counters.values():
                parts.append(c.family.render())
            for h in self._histograms.values():
                parts.append(h.family.render())
            for g in self._gauges.values():
                parts.append(g.family.render())
        return "\n".join(p for p in parts if p)


# ---------------- 全局装配 ----------------

_default_collector: Optional[MetricsCollector] = None


def get_default_collector() -> MetricsCollector:
    """获取默认指标收集器（懒加载，默认 NoOp 零影响）。"""
    global _default_collector
    if _default_collector is None:
        _default_collector = NoOpCollector()
    return _default_collector


def set_default_collector(collector: MetricsCollector) -> None:
    """替换默认收集器。"""
    global _default_collector
    _default_collector = collector


def enable_prometheus_collector() -> PrometheusTextCollector:
    """启用 Prometheus 文本收集器为默认（幂等，返回单例）。

    /metrics 端点调用 get_default_collector().render() 即可。
    """
    global _default_collector
    existing = _default_collector
    if isinstance(existing, PrometheusTextCollector):
        return existing
    pc = PrometheusTextCollector()
    _default_collector = pc
    return pc


def reset_default_collector() -> None:
    """重置为 NoOp（测试用）。"""
    global _default_collector
    _default_collector = NoOpCollector()


# 关键 SLO 指标名常量（roadmap §7.2）
SLO_TX_ROLLBACK_RATE = "tx_rollback_rate"
SLO_TX_DURATION_SECONDS = "tx_duration_seconds"
SLO_TX_COMPENSATION_TRIGGERED = "tx_compensation_triggered_total"
SLO_AGENT_RECALL_HIT_RATE = "agent_recall_hit_rate"
