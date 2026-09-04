# M5 — 可观测性对齐企业（P5，零依赖版）设计

- Status: Approved
- Date: 2026-09-04
- Milestone: M5 / P5（路线图 §7）
- 关联路线图: `docs/superpowers/specs/2026-09-03-enterprise-readiness-roadmap.md`

---

## 1. 目标与范围

企业级可观测性：SLO 业务指标（事务回滚率/时长/补偿）可被 Prometheus 抓取；trace 可（可选）接入 Jaeger/Tempo。

**M5 验收（roadmap §7.5 修正为少依赖形态）**：
- [ ] `/metrics` 输出 Prometheus 文本格式（SLO 指标可 dashboard）
- [ ] coordinator commit/rollback 自动发指标
- [ ] 开发默认（NoOp/JSONL/HTML）不受影响
- [ ] 零新增依赖（纯标准库）

**放弃项**（用户决策：少依赖优先于 roadmap "OTel SDK"）：
- opentelemetry-python SDK（不引入）
- prometheus_client（用自研渲染替代）

---

## 2. 关键决策

| 决策项 | 结论 |
|--------|------|
| 依赖策略 | 零新增（纯标准库） |
| metrics | `PrometheusTextCollector`（自研内存 metric + Prometheus 文本渲染） |
| SLO 指标 | tx_rollback_total / tx_duration_seconds / tx_compensation_triggered_total / agent_recall_hit_rate |
| trace 保留 | 现有 JSONL/HTML 不动 |
| OTLP | `OTLPHttpJsonExporter`（可选，默认关，纯标准库发 Jaeger/Tempo） |
| 埋点 | coordinator commit/rollback 指标 + Agent/事务 tx_id 关联 attribute |

---

## 3. 架构

```
agentorchestra/observability/
├── trace_logger.py        # 现有（不动）
├── otel_exporter.py       # 骨架 → OTLPHttpJsonExporter（默认关，纯标准库）
├── metrics.py             # 骨架 → PrometheusTextCollector + NoOp 默认
├── slo.py                 # 现有 dataclass（保持 + 映射常量）
└── prometheus.py          # 新增：Prometheus 文本渲染器（自研，零依赖）
```

---

## 4. 模块职责

### 4.1 prometheus.py（渲染器，零依赖）

```python
class MetricFamily:      # name / help / type / samples
class Counter:           # inc / value
class Histogram:         # observe / 预置 buckets
def render_text(families) -> str:
    # "# HELP ...\n# TYPE ... counter|histogram\nname{labels} value\n"
```

### 4.2 metrics.py（SLO collector）

```python
class PrometheusTextCollector(MetricsCollector):
    """内存 metric + render() 输出 Prometheus 文本。"""
    def increment(name, value=1, labels=None)   # counter
    def observe(name, value, labels=None)        # histogram
    def gauge(name, value, labels=None)          # gauge
    def render() -> str                          # 完整文本

class NoOpCollector(MetricsCollector): ...       # 默认，零影响

def get_default_collector() -> MetricsCollector: ...
def set_default_collector(c) -> None: ...
def enable_prometheus_collector() -> PrometheusTextCollector:  # 装配单例
```

### 4.3 otel_exporter.py（trace → Jaeger/Tempo，可选）

```python
class OTLPHttpJsonExporter(SpanExporter):
    """core.tracing.Span → OTLP/HTTP JSON → POST（默认关）。"""
    def __init__(self, endpoint="http://localhost:4318/v1/traces",
                 service_name="agentorchestra"): self.enabled = False
    def export(self, span):  # 构造 OTLP JSON resourceSpans，urllib POST
    def enable(self): self.enabled = True
```

OTLP/HTTP JSON 载荷结构（resourceSpans → scopeSpans → spans），span 含 traceId/spanId/parentSpanId/name/attributes/status。

### 4.4 coordinator 埋点（coordinator.py）

```python
# _commit / _compensate_and_fail 内：
col = get_default_collector()
col.observe("tx_duration_seconds", elapsed, {"result": "committed"|"aborted"})
# commit 失败/回滚时：
col.increment("tx_rollback_total", 1, {"reason": ...})
col.increment("tx_compensation_triggered_total", 1, {"action": ...})
```

`get_default_collector()` 默认 NoOp → 无配置零影响（向后兼容）。

---

## 5. monitor 集成

`core/monitor.py` 的 `/metrics` 端点改为：
- 若 `get_default_collector()` 是 PrometheusTextCollector → 返回 `render()`
- 否则回退现有逻辑

---

## 6. 测试策略（tests/observability/）

| 文件 | 覆盖 |
|------|------|
| test_prometheus_render.py | 文本格式（HELP/TYPE/counter/histogram/gauge 语法） |
| test_metrics_collector.py | increment/observe/gauge + NoOp 兜底 + render |
| test_otel_exporter.py | OTLP JSON 载荷结构（mock transport，不真发） |
| test_coordinator_metrics.py | coordinator commit/rollback 触发指标（NoOp 零影响 + Prometheus 计数） |

现有 337 测试必须全绿。

---

## 7. 验收标准

- [ ] `pytest tests/observability/` 全绿
- [ ] `pytest tests/`（现有 337）全绿
- [ ] ruff + mypy
- [ ] /metrics Prometheus 文本可 dashboard
- [ ] 默认 NoOp → 零影响
- [ ] 零新增依赖

---

## 8. 实施步骤

1. observability/prometheus.py 渲染器
2. metrics.py PrometheusTextCollector + enable_prometheus_collector
3. otel_exporter.py OTLPHttpJsonExporter（默认关）
4. coordinator.py 埋点
5. monitor.py /metrics 集成
6. tests/observability/
7. 全量回归 + lint + mypy
8. 提交

---

## 9. 风险与回退

- **指标文本兼容**：自研渲染遵循 Prometheus text exposition 规范（简单子集足够）
- **OTLP JSON**：企业后端需支持 OTLP/HTTP JSON（Jaeger/Tempo 现支持）；默认关避免误发
- **NoOp 默认**：未显式 enable 前指标不采（向后兼容）；enable_prometheus_collector() 显式开启