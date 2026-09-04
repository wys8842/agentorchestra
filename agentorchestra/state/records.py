"""records - 锁 / 幂等键 / DLQ 记录类型（M1 事务引擎用）。

放在 state 包内，使 CheckpointStore 抽象能引用它们而不引入对 tx/ 的反向依赖。
设计见 docs/superpowers/specs/2026-09-03-m1-transaction-runtime-design.md §4.1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class LockRecord:
    """乐观锁记录（locks 表）。

    Attributes:
        resource_key: 被锁资源键（如 "order:12345"）
        version: 当前版本号（CAS 基准）
        owner_tx: 持有锁的事务 id
        held_since: 获取时间
        expires_at: 过期时间（TTL 释放）
    """

    resource_key: str
    version: int
    owner_tx: str
    held_since: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None


@dataclass
class IdempotencyRecord:
    """幂等键记录（idempotency_keys 表）。

    Attributes:
        idempotency_key: 幂等键（必填；未显式传时自动生成）
        request_hash: 请求签名哈希
        tx_id: 关联事务 id
        status: running | completed | failed
        result: 首次执行的返回结果（completed 后重放返回它）
        created_at: 创建时间
        expires_at: TTL 过期时间（默认 24h）
    """

    idempotency_key: str
    request_hash: str
    tx_id: Optional[str] = None
    status: str = "running"
    result: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None


@dataclass
class DLQEntry:
    """死信条目（dead_letter 表）。

    Attributes:
        tx_id: 关联事务 id
        action_name: 补偿失败的动作名
        error: 最后一次错误信息
        attempts: 已尝试补偿次数
        status: open | resolved
        created_at: 入队时间
        resolved_at: 人工解决时间
    """

    tx_id: str
    action_name: str
    error: Optional[str] = None
    attempts: int = 0
    status: str = "open"
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None
