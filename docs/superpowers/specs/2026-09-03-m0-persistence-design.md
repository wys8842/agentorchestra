# M0 — 持久化与恢复（durable checkpoint）设计

- Status: Approved
- Date: 2026-09-03
- Milestone: M0 / P0（路线图 §2）
- 关联路线图: `docs/superpowers/specs/2026-09-03-enterprise-readiness-roadmap.md`

---

## 1. 目标与范围

把 `agentorchestra` 的"内存上下文"升级为 **durable checkpoint**：

- Agent 跑崩 / Pod 被 kill 后能从最近 checkpoint 恢复
- Ontology 物化变更走 WAL（崩溃可恢复骨架，M1 完善补偿语义）
- HITL 中断通过 `interrupt(resume_token)` 协议实现
- 现有 `session_store.py` 保留为 `InMemoryCheckpointStore` 兼容层

**不在本里程碑范围**：

- M1 事务引擎的补偿/DLQ（仅在 WAL 留 hook）
- M2+ 的 DAG 通信、多租户隔离

---

## 2. 关键决策（用户确认）

| 决策项 | 结论 | 理由 |
|--------|------|------|
| 依赖策略 | **SQLAlchemy 2.0 + asyncpg 必装** | roadmap §1.1 P1 唯一可接受重依赖 |
| 状态后端 | **PG（生产）/ SQLite（默认零配置）** | roadmap §2.2 |
| 默认行为 | **默认开启持久化（SQLite 本机）** | 与 roadmap §2.5 验收对齐 |
| 兼容层 | **session_store.py → InMemoryCheckpointStore** | 保留 `persistence_mode='in_memory'` 选项 |
| interrupt 协议 | **UUIDv4 token + metadata JSON 存表** | 简单可靠，全局唯一 |
| 快照策略 | **双阈值（1000 条 WAL OR 60s）** + 后台 asyncio 任务 | roadmap §2.2 |
| M5 范围 | **本会话仅放骨架接口 + NoOp** | 避免本会话预算超支 |

---

## 3. 架构（包结构）

```
agentorchestra/state/                  # 新顶层包
├── __init__.py                       # 公共 API
├── checkpoint.py                     # Checkpoint 数据类 + CheckpointStore 抽象
├── thread.py                         # ThreadManager
├── wal.py                            # append-only WAL
├── interrupt.py                      # HITL 中断与恢复
├── snapshot.py                       # 周期快照压缩 + 后台任务
└── backends/
    ├── __init__.py
    ├── sqlalchemy_base.py            # SQLAlchemy 2.0 async 基类
    ├── sqlite_backend.py             # 默认（aiosqlite）
    ├── postgres_backend.py           # 生产（asyncpg）
    └── memory_backend.py             # InMemory（兼容层）

agentorchestra/observability/          # M5 骨架（横切）
├── trace_logger.py                    # 现有，不动
├── otel_exporter.py                  # 新：Exporter 抽象 + NoOpExporter
├── metrics.py                        # 新：MetricsCollector 抽象 + NoOpCollector
└── slo.py                            # 新：SLO 指标 dataclass
```

---

## 4. 数据模型

### 4.1 表 schema

```sql
CREATE TABLE threads (
    thread_id   TEXT PRIMARY KEY,
    created_at  TIMESTAMP NOT NULL,
    updated_at  TIMESTAMP NOT NULL,
    metadata    JSON,
    status      TEXT  -- 'active' | 'interrupted' | 'completed' | 'failed'
);

CREATE TABLE checkpoints (
    thread_id     TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    parent_id     TEXT,
    state         JSON NOT NULL,
    metadata      JSON,
    created_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_id)
);
CREATE INDEX idx_checkpoints_thread_created
    ON checkpoints(thread_id, created_at DESC);

CREATE TABLE wal (
    wal_id        BIGSERIAL PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    sequence_no   BIGINT NOT NULL,
    action_type   TEXT NOT NULL,
    payload       JSON NOT NULL,
    tx_id         TEXT,
    created_at    TIMESTAMP NOT NULL,
    UNIQUE (thread_id, sequence_no)
);
CREATE INDEX idx_wal_thread_seq ON wal(thread_id, sequence_no);

CREATE TABLE snapshots (
    thread_id     TEXT NOT NULL,
    snapshot_id   TEXT NOT NULL,
    up_to_seq     BIGINT NOT NULL,
    state         JSON NOT NULL,
    metadata      JSON,
    created_at    TIMESTAMP NOT NULL,
    PRIMARY KEY (thread_id, snapshot_id)
);

CREATE TABLE interrupts (
    token         TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    reason        TEXT NOT NULL,
    payload       JSON,
    status        TEXT NOT NULL,
    response      JSON,
    created_at    TIMESTAMP NOT NULL,
    resolved_at   TIMESTAMP
);
```

### 4.2 关键约束

- `wal.sequence_no` 单调递增（崩溃恢复时用于断点检测）
- `snapshots.up_to_seq` 表示快照代表 WAL 中前 N 条已应用
- `interrupts.token` 是 UUIDv4，全局唯一
- 恢复算法：找最新 snapshot → replay WAL 中 `sequence_no > up_to_seq` 的 checkpoint 条目

---

## 5. API 形态

```python
# 默认走 SQLite 本机零配置
from agentorchestra.state import get_default_store, ThreadManager

store = get_default_store()
# 等价于 get_default_store("sqlite+aiosqlite:///./agent_state.db")
# 也支持 "postgresql+asyncpg://user:pwd@host/db"

manager = ThreadManager(store=store)
thread_id = manager.create_thread(metadata={"user": "alice"})

# Agent 自动接入
agent = ReActAgent(name="x", llm=llm, tool_registry=registry)
result = agent.run("...")  # 每步 _save_checkpoint

# 显式 resume
agent.resume(thread_id="...", checkpoint_id="...")

# HITL
from agentorchestra.state import InterruptPending
try:
    result = agent.run("...")
except InterruptPending as e:
    # 业务侧：agent.resume_with(e.token, response={"approved": True})
    ...
```

### 5.1 CheckpointStore 抽象

```python
class CheckpointStore(ABC):
    async def init(self) -> None: ...
    async def close(self) -> None: ...

    # Thread
    async def create_thread(self, thread_id: str, metadata: dict) -> None: ...
    async def get_thread(self, thread_id: str) -> Optional[ThreadState]: ...
    async def update_thread_status(self, thread_id: str, status: str) -> None: ...

    # Checkpoint
    async def save_checkpoint(self, cp: Checkpoint) -> None: ...
    async def load_checkpoint(self, thread_id: str, checkpoint_id: str) -> Optional[Checkpoint]: ...
    async def list_checkpoints(self, thread_id: str, limit: int = 50) -> List[Checkpoint]: ...
    async def latest_checkpoint(self, thread_id: str) -> Optional[Checkpoint]: ...

    # WAL
    async def append_wal(self, entry: WALEntry) -> int: ...    # 返回 sequence_no
    async def read_wal(self, thread_id: str, after_seq: int = 0, limit: int = 1000) -> List[WALEntry]: ...

    # Snapshot
    async def save_snapshot(self, snap: Snapshot) -> None: ...
    async def latest_snapshot(self, thread_id: str) -> Optional[Snapshot]: ...

    # Interrupt
    async def create_interrupt(self, intr: Interrupt) -> None: ...
    async def resolve_interrupt(self, token: str, response: dict) -> None: ...
    async def get_interrupt(self, token: str) -> Optional[Interrupt]: ...
```

---

## 6. 接入点

| 现有组件 | 接入方式 |
|---------|---------|
| `core/agent.py:Agent.run()` | 每步 `_save_checkpoint(thread_id, state)` 同步刷盘（thread_id 复用 session_id） |
| `core/agent.py:Agent.arun()` | 异步 checkpoint 写入（不阻塞主流程） |
| `core/agent.py` | 新增 `resume(thread_id, checkpoint_id)` 与 `resume_with(token, response)` |
| `core/session_store.py` | 重构为实现 `InMemoryCheckpointStore`（保留旧 API：save/load/list_sessions/delete） |
| `ontology/storage/object_store.py` | 提供 `wal_hook` 回调，所有 insert/update/delete 走 WAL |
| `ontology/engine.py` | `MaterializationManager.register_target` 触发的对象变更打 WAL |
| `core/config.py` | 新增 `persistence_mode`、`state_db_url`、`wal_snapshot_threshold`、`wal_snapshot_interval_seconds` |

### 6.1 Agent 接入细节

- `Agent.__init__` 末尾实例化 `CheckpointStore`（按 config 选择 backend）
- `Agent.run()` 入口若 `thread_id` 已存在（且有未完成 checkpoint），自动 resume；否则创建新 thread
- 每一步 `_save_checkpoint`：state = `{"history": [...], "step": N, "messages_hash": "..."}`
- 异常时 `_save_checkpoint(state, status="failed")` 写入失败态

### 6.2 Ontology 接入细节

- `ObjectStore` 增加 `wal_hook: Callable[[WALEntry], Awaitable[None]]` 字段
- `insert/update/delete` 调用前先发 WAL 条目（`action_type='state_update'`，payload 含 object_type/pk/before/after）
- M0 阶段：失败仅记录、不阻断；M1 阶段：事务引擎接管

---

## 7. 测试策略

新增 `tests/state/`：

| 文件 | 覆盖 |
|------|------|
| `test_wal.py` | WAL 追加 + 顺序号唯一性 + 重放 |
| `test_checkpoint.py` | 创建/恢复/parent_id 链 |
| `test_snapshot.py` | 双阈值触发 + 压缩 WAL |
| `test_thread.py` | ThreadManager 生命周期 |
| `test_interrupt.py` | UUIDv4 token + resume 协议 |
| `test_crash_recovery.py` | 模拟 kill → 新 store → resume |
| `test_ontology_wal.py` | Ontology 物化走 WAL |
| `test_session_store_compat.py` | 兼容层保持旧 API |

辅助：

- `tests/state/conftest.py` 提供 SQLite in-memory backend fixture
- 测试用 `:memory:` 或临时文件，CI 干净

---

## 8. 验收标准

- [ ] `pytest tests/state/` 全部通过
- [ ] `pytest tests/`（现有 182 测试）全部通过
- [ ] `Agent.run()` 中途抛异常后 `agent.resume()` 能从最近 LLM 响应继续
- [ ] 默认 SQLite 即开即用（`pip install -e .` 后无配置即可跑）
- [ ] `persistence_mode='in_memory'` 不引入任何 DB 依赖
- [ ] `ruff check` + `mypy agentorchestra/state` 通过

---

## 9. 实施步骤

1. `pyproject.toml` 加依赖：`sqlalchemy>=2.0`、`aiosqlite`、`asyncpg`（PG 可选）
2. 写 `state/` 包：抽象 → backend → 组件 → Agent/Ontology 接入
3. 写 `tests/state/` 全套测试
4. 跑全量测试 + lint + type check
5. 提交

---

## 10. 风险与回退

- **现有 182 测试破坏**：通过保留 session_store.py 旧 API（`InMemoryCheckpointStore`）兜底
- **SQLite async 性能**：aiosqlite 单连接足够 M0 验收；高频场景后切 PG
- **Agent 接入的 session_id 复用**：若历史 session_id 不存在，优雅降级为新建（不抛错）
- **WAL 体积无限增长**：双阈值快照压缩 + 配置项可调