"""WAL - append-only Write-Ahead Log。

设计见 docs/superpowers/specs/2026-09-03-m0-persistence-design.md §4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class WALActionType(str, Enum):
    """WAL 动作类型。

    - CHECKPOINT: 写入一个新 checkpoint（同时存 checkpoints 表与 WAL）
    - STATE_UPDATE: 状态增量变化（ObjectStore 写操作）
    - INTERRUPT: 触发 HITL 中断
    - RESUME: resume 中断（含 response）
    - SNAPSHOT: 写入周期快照（标记压缩点）
    """

    CHECKPOINT = "checkpoint"
    STATE_UPDATE = "state_update"
    INTERRUPT = "interrupt"
    RESUME = "resume"
    SNAPSHOT = "snapshot"


@dataclass
class WALEntry:
    """WAL 单条记录。

    Attributes:
        thread_id: 所属 thread
        action_type: 动作类型
        payload: 任意 JSON 可序列化数据
        sequence_no: 单调递增（写入时由 store 分配）
        tx_id: 关联事务 id（M1 使用，M0 留 None）
        created_at: 创建时间
    """

    thread_id: str
    action_type: WALActionType
    payload: Dict[str, Any]
    sequence_no: int = 0
    tx_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "sequence_no": self.sequence_no,
            "action_type": self.action_type.value
            if isinstance(self.action_type, WALActionType)
            else str(self.action_type),
            "payload": self.payload,
            "tx_id": self.tx_id,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WALEntry":
        at = d.get("action_type", "checkpoint")
        if isinstance(at, str):
            at = WALActionType(at)
        return cls(
            thread_id=d["thread_id"],
            action_type=at,
            payload=d.get("payload", {}),
            sequence_no=int(d.get("sequence_no", 0)),
            tx_id=d.get("tx_id"),
            created_at=datetime.fromisoformat(d["created_at"])
            if isinstance(d.get("created_at"), str)
            else d.get("created_at", datetime.now()),
        )
