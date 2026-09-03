"""SLO 指标定义（M5 横切骨架）。

定义业务可观测指标：补偿触发率、事务回滚率、平均事务时长、Agent 召回命中率。
后续会话接 Prometheus / OTel metrics 时复用这些 dataclass。

Roadmap §7.2 决策：业务可观测指标覆盖事务体系与 Agent 关键路径。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List


class SLOType(str, Enum):
    """SLO 类型。

    - COUNTER: 单调递增计数（事务回滚次数、补偿触发次数）
    - HISTOGRAM: 分布观测（事务时长、LLM 延迟）
    - GAUGE: 瞬时值（命中率、配额剩余）
    """

    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"


@dataclass(frozen=True)
class SLODefinition:
    """单个 SLO 指标定义。"""

    name: str
    slo_type: SLOType
    description: str
    unit: str = ""
    labels: List[str] = field(default_factory=list)


# 业务 SLO 指标定义（roadmap §7.2）
SLO_DEFINITIONS: Dict[str, SLODefinition] = {
    "tx_rollback_rate": SLODefinition(
        name="tx_rollback_rate",
        slo_type=SLOType.GAUGE,
        description="事务回滚率（rollback_count / commit_count）",
        unit="ratio",
        labels=["tenant_id"],
    ),
    "tx_duration_seconds": SLODefinition(
        name="tx_duration_seconds",
        slo_type=SLOType.HISTOGRAM,
        description="事务从开始到 commit/rollback 的耗时分布",
        unit="s",
        labels=["tenant_id", "result"],
    ),
    "tx_compensation_triggered_total": SLODefinition(
        name="tx_compensation_triggered_total",
        slo_type=SLOType.COUNTER,
        description="补偿动作触发次数",
        unit="count",
        labels=["tenant_id", "action"],
    ),
    "agent_recall_hit_rate": SLODefinition(
        name="agent_recall_hit_rate",
        slo_type=SLOType.GAUGE,
        description="Memory 召回命中率（命中数 / 总请求数）",
        unit="ratio",
        labels=["agent_name", "namespace"],
    ),
}
