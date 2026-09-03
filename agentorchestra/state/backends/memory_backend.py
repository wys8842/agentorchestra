"""InMemory backend - 兼容层。

保留现有 session_store.py 的行为。零 DB 依赖。
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..checkpoint import Checkpoint, CheckpointStore
from ..interrupt import Interrupt, InterruptStatus
from ..snapshot import Snapshot
from ..thread import ThreadStatus
from ..wal import WALEntry


class InMemoryCheckpointStore(CheckpointStore):
    """内存 CheckpointStore。

    - 线程安全（threading.Lock）
    - 零依赖、可序列化（to_dict/from_dict）
    - 用于：
        1. 默认 `persistence_mode='in_memory'`（无 DB 依赖）
        2. session_store.py 兼容层
        3. 单元测试
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._threads: Dict[str, Dict[str, Any]] = {}
        self._checkpoints: Dict[str, Dict[str, Checkpoint]] = {}  # thread_id -> {cp_id -> Checkpoint}
        self._wal: Dict[str, List[WALEntry]] = {}
        self._snapshots: Dict[str, List[Snapshot]] = {}
        self._interrupts: Dict[str, Interrupt] = {}

    async def init(self) -> None:
        return None

    async def close(self) -> None:
        return None

    # ---------------- Thread ----------------

    async def create_thread(
        self, thread_id: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        with self._lock:
            if thread_id in self._threads:
                return  # 已存在：忽略
            now = datetime.now()
            self._threads[thread_id] = {
                "thread_id": thread_id,
                "created_at": now,
                "updated_at": now,
                "metadata": dict(metadata or {}),
                "status": ThreadStatus.ACTIVE.value,
            }

    async def get_thread(self, thread_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            t = self._threads.get(thread_id)
            if not t:
                return None
            return {
                "thread_id": t["thread_id"],
                "status": t["status"],
                "created_at": t["created_at"].isoformat(),
                "updated_at": t["updated_at"].isoformat(),
                "metadata": dict(t["metadata"]),
            }

    async def update_thread_status(self, thread_id: str, status: str) -> None:
        with self._lock:
            t = self._threads.get(thread_id)
            if t:
                t["status"] = status
                t["updated_at"] = datetime.now()

    # ---------------- Checkpoint ----------------

    async def save_checkpoint(self, cp: Checkpoint) -> None:
        with self._lock:
            self._checkpoints.setdefault(cp.thread_id, {})[cp.checkpoint_id] = cp

    async def load_checkpoint(
        self, thread_id: str, checkpoint_id: str
    ) -> Optional[Checkpoint]:
        with self._lock:
            cps = self._checkpoints.get(thread_id, {})
            return cps.get(checkpoint_id)

    async def list_checkpoints(
        self, thread_id: str, limit: int = 50
    ) -> List[Checkpoint]:
        with self._lock:
            cps = self._checkpoints.get(thread_id, {})
            ordered = sorted(cps.values(), key=lambda c: c.created_at, reverse=True)
            return ordered[:limit]

    async def latest_checkpoint(self, thread_id: str) -> Optional[Checkpoint]:
        cps = await self.list_checkpoints(thread_id, limit=1)
        return cps[0] if cps else None

    # ---------------- WAL ----------------

    async def append_wal(self, entry: WALEntry) -> int:
        with self._lock:
            seqs = self._wal.setdefault(entry.thread_id, [])
            seq = (seqs[-1].sequence_no if seqs else 0) + 1
            entry.sequence_no = seq
            seqs.append(entry)
            return seq

    async def read_wal(
        self, thread_id: str, after_seq: int = 0, limit: int = 1000
    ) -> List[WALEntry]:
        with self._lock:
            seqs = self._wal.get(thread_id, [])
            result = [e for e in seqs if e.sequence_no > after_seq]
            return result[:limit]

    async def max_wal_seq(self, thread_id: str) -> int:
        with self._lock:
            seqs = self._wal.get(thread_id, [])
            return seqs[-1].sequence_no if seqs else 0

    # ---------------- Snapshot ----------------

    async def save_snapshot(self, snap: Snapshot) -> None:
        with self._lock:
            self._snapshots.setdefault(snap.thread_id, []).append(snap)

    async def latest_snapshot(self, thread_id: str) -> Optional[Snapshot]:
        with self._lock:
            snaps = self._snapshots.get(thread_id, [])
            return snaps[-1] if snaps else None

    # ---------------- Interrupt ----------------

    async def create_interrupt(self, intr: Interrupt) -> None:
        with self._lock:
            self._interrupts[intr.token] = intr

    async def resolve_interrupt(self, token: str, response: Dict[str, Any]) -> None:
        with self._lock:
            intr = self._interrupts.get(token)
            if intr:
                intr.status = InterruptStatus.RESUMED
                intr.response = response
                intr.resolved_at = datetime.now()

    async def get_interrupt(self, token: str) -> Optional[Interrupt]:
        with self._lock:
            return self._interrupts.get(token)
