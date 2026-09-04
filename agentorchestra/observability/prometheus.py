"""prometheus - Prometheus 文本格式渲染器（M5，零依赖）。

纯标准库实现 Prometheus text exposition format 子集：
- Counter / Gauge / Histogram
- render_text() 输出 "# HELP/# TYPE/样本行"

参考规范：https://prometheus.io/docs/instrumenting/exposition_formats/
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple


def _escape_label_value(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(labels: Optional[Dict[str, str]]) -> str:
    if not labels:
        return ""
    parts = ", ".join(
        f'{k}="{_escape_label_value(v)}"' for k, v in sorted(labels.items())
    )
    return "{" + parts + "}"


class _MetricFamily:
    """单个指标族的样本集合（按标签区分样本）。"""

    _buckets: List[float] = []  # histogram 预置桶

    def __init__(self, name: str, help_text: str, metric_type: str):
        self.name = name
        self.help = help_text
        self.metric_type = metric_type  # counter | gauge | histogram
        self._labels: Dict[str, Dict[str, str]] = {}  # labels_key -> labels
        self._values: Dict[str, Any] = {}
        self._buckets: List[float] = []
        self._lock = threading.RLock()

    def _key(self, labels: Optional[Dict[str, str]]) -> str:
        return str(sorted((labels or {}).items()))

    # ---------------- counter / gauge ----------------

    def set_value(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            k = self._key(labels)
            self._labels_cache(k, labels)
            self._values[k] = float(value)

    def add(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            k = self._key(labels)
            self._labels_cache(k, labels)
            self._values[k] = self._values.get(k, 0.0) + float(value)

    # ---------------- histogram ----------------

    def _ensure_histogram(self, labels) -> Tuple[str, Dict[str, str], Dict]:
        k = self._key(labels)
        if k not in self._values:
            # histogram 样本结构存于 _values[k] = {"count","sum","buckets":{le:count}}
            self._values[k] = {"count": 0.0, "sum": 0.0,
                               "buckets": {}}  # type: ignore[assignment]
        self._labels_cache(k, labels)
        return k, (labels or {}), self._values[k]  # type: ignore[return-value]

    def observe(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        with self._lock:
            k, _lb, agg = self._ensure_histogram(labels)
            agg["count"] += 1
            agg["sum"] += float(value)
            # +Inf bucket
            buckets = agg["buckets"]
            for le in self._buckets:
                if float(value) <= le:
                    buckets[le] = buckets.get(le, 0) + 1
            buckets["+Inf"] = buckets.get("+Inf", 0) + 1

    def _labels_cache(self, k: str, labels: Optional[Dict[str, str]]) -> None:
        if k not in self._labels and labels is not None:
            self._labels[k] = dict(labels)

    def render(self) -> str:
        lines = [f"# HELP {self.name} {self.help}",
                 f"# TYPE {self.name} {self.metric_type}"]
        with self._lock:
            for k, v in self._values.items():
                labels = self._labels.get(k, {})
                lstr = _format_labels(labels)
                if isinstance(v, dict):  # histogram
                    count = v["count"]
                    s = v["sum"]
                    for le in list(self._buckets) + ["+Inf"]:
                        if le in v["buckets"]:
                            le_labels = _format_labels({**labels, "le": str(le)})
                            lines.append(
                                f"{self.name}_bucket{le_labels} {v['buckets'][le]:g}")
                    lines.append(f"{self.name}_sum{lstr} {s:g}")
                    lines.append(f"{self.name}_count{lstr} {count:g}")
                else:
                    lines.append(f"{self.name}{lstr} {v:g}")
        return "\n".join(lines)


class Counter:
    """Prometheus Counter。"""

    def __init__(self, name: str, documentation: str = ""):
        self.family = _MetricFamily(name, documentation or name, "counter")

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        self.family.add(amount, labels)

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        k = str(sorted((labels or {}).items()))
        v = self.family._values.get(k)
        return float(v) if not isinstance(v, dict) and v is not None else 0.0


class Gauge:
    """Prometheus Gauge。"""

    def __init__(self, name: str, documentation: str = ""):
        self.family = _MetricFamily(name, documentation or name, "gauge")

    def set(self, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        self.family.set_value(value, labels)

    def inc(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        self.family.add(amount, labels)

    def dec(self, amount: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        self.family.add(-amount, labels)


class Histogram:
    """Prometheus Histogram（预置桶）。"""

    def __init__(self, name: str, documentation: str = "",
                 buckets: Optional[List[float]] = None):
        self.family = _MetricFamily(name, documentation or name, "histogram")
        self.family._buckets = buckets or [
            0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10
        ]

    def observe(self, amount: float, labels: Optional[Dict[str, str]] = None) -> None:
        self.family.observe(amount, labels)


__all__ = ["Counter", "Gauge", "Histogram", "_MetricFamily"]
