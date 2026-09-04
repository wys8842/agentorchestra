# state — 持久化与恢复（P0 / M0）

把框架的"内存上下文"升级为 **durable checkpoint**：Agent 跑崩 / Pod 被 kill 后可从断点恢复；WAL 记录一切状态变更。

设计见 [M0 spec](../superpowers/specs/2026-09-03-m0-persistence-design.md)。

## 模块组成

| 文件 | 职责 |
|------|------|
| `checkpoint.py` | `Checkpoint` 数据类 + `CheckpointStore` 抽象（线程/WAL/快照/中断/审计统一接口） |
| `wal.py` | `WALEntry` + `WALActionType`：append-only 日志（checkpoint/state_update/interrupt/resume/snapshot/tx_begin/tx_commit） |
| `thread.py` | `ThreadManager` / `ThreadState`：一个 thread = 一个会话/任务实例 |
| `interrupt.py` | HITL 中断与恢复（`InterruptPending` + token 协议） |
| `snapshot.py` | 周期快照压缩 WAL（双阈值：条数 or 时间） |
| `records.py` | `LockRecord` / `IdempotencyRecord` / `DLQEntry` / `InboxMessage` / `AuditEntry` 记录类型 |
| `backends/` | `sqlalchemy_base`（SQLAlchemy 2.0 async 基类）· `sqlite_backend`（默认零配置）· `postgres_backend`（生产）· `memory_backend`（InMemory 兼容层） |

## 快速开始

```python
from agentorchestra.state import get_default_store, ThreadManager

# 默认 SQLite 本机零配置（agent_state.db）
store = get_default_store()

manager = ThreadManager(store=store)
thread_id = await manager.create_thread(metadata={"user": "alice"})
```

显式后端：

```python
get_default_store("sqlite+aiosqlite:///./agent_state.db")          # SQLite
get_default_store("postgresql+asyncpg://user:pwd@host/db")          # PG
get_default_store("in_memory://")                                   # 无 DB
```

## CheckpointStore 接口分组

| 分组 | 方法 |
|------|------|
| Thread | `create_thread` / `get_thread` / `update_thread_status` |
| Checkpoint | `save_checkpoint` / `load_checkpoint` / `list_checkpoints` / `latest_checkpoint` |
| WAL | `append_wal` / `read_wal` / `max_wal_seq` |
| Snapshot | `save_snapshot` / `latest_snapshot` |
| Interrupt | `create_interrupt` / `resolve_interrupt` / `get_interrupt` |
| 锁（M1） | `acquire_lock` / `compare_and_swap` / `release_lock` / `read_version` |
| 幂等（M1） | `put_idempotency` / `get_idempotency` / `delete_expired_idempotency` |
| DLQ（M1） | `enqueue_dlq` / `list_dlq` |
| Inbox（M2） | `enqueue_message` / `list_pending_messages` / `mark_delivered` / `mark_failed` / `ack_message` / `delete_expired_messages` |
| 审计（M3 WORM） | `append_audit` / `query_audit`（无 update/delete，接口层保证 WORM） |

## Agent 接入（M0）

`core/agent.py` 在 `state_checkpoint_enabled=True` 时自动初始化 store，并暴露：

```python
agent = ReActAgent(...)
cp_id = await agent._save_checkpoint(thread_id, {"history": [...], "step": 1}, step=1)
state = await agent.resume(thread_id)             # 从最新 checkpoint 恢复
await agent.resume_with(token, response)          # HITL resume
```

崩溃恢复：Agent 中途 kill → 重建 store → `latest_checkpoint` 取最近状态 → 续跑。

## HITL interrupt

```python
from agentorchestra.state import InterruptPending
try:
    await agent.arun("...")
except InterruptPending as e:
    print(f"等待审批 token: {e.token}")
    # 业务侧：await agent.resume_with(e.token, {"approved": True})
```

## 配置

见 `core/config.py`：`persistence_mode`（sqlite/postgres/in_memory）、`state_db_url`、`state_checkpoint_enabled`、`wal_snapshot_*`。
