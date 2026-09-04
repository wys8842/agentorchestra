# M1 — 事务引擎运行时（P1）设计

- Status: Approved
- Date: 2026-09-04
- Milestone: M1 / P1（路线图 §3）
- 依赖: M0（`agentorchestra.state` WAL / CheckpointStore）
- 关联路线图: `docs/superpowers/specs/2026-09-03-enterprise-readiness-roadmap.md`

---

## 1. 目标与范围

把 `ontology/process/transaction.py` 的 `TransactionManager.register/execute` 从"接口壳"升级为真正的**事务运行时**：

- 幂等键（哈希去重 + TTL 24h）
- WAL 落库（复用 M0 `state.wal` + `tx_id`）
- 两阶段补偿（逆序 + 重试 N 次）
- Dead-letter（补偿耗尽入库 + 监控）
- 乐观锁（自研 locks 表 CAS）

**不在本里程碑范围**：

- SSI 快照隔离 / 悲观锁降级（仅留 `isolation.py` 接口）
- 分布式协调 / 多节点（单机版起步，roadmap §1.3）
- 对象内嵌 `version`（M3 做对象身份）

---

## 2. 关键决策（用户确认）

| 决策项 | 结论 |
|--------|------|
| 覆盖边界 | 最小可用运行时（coordinator + idempotency + compensation + DLQ + optimistic lock） |
| WAL 载体 | 复用 `state.wal` + `tx_id` 字段；`WALActionType` 增 `TX_BEGIN` / `TX_COMMIT` |
| 幂等/DLQ 存储 | 扩展 `CheckpointStore` 加 `locks` / `idempotency_keys` / `dead_letter` 三表；key 必填但自动生成 |
| 乐观锁 | 自研 `locks` 表（resource_key + version + owner_tx） |
| 并发形态 | async 核心 + `sync_transaction()` 桥接（旧 execute 内部替换） |
| sync 无 store | 旧 execute 不传 store 时用 in-memory 协调器（保旧测试不落 DB） |
| 补偿重试 | 默认 3 次 + 固定退避，coordinator 构造参数可配 |

---

## 3. 包结构

```
agentorchestra/tx/
├── __init__.py          # 公共 API
├── coordinator.py       # TransactionCoordinator（async 核心）
├── context.py           # TxContext / TxAction / TxAbort / TxConflict / TxStatus
├── sync.py              # run_sync() 桥接（供旧 sync execute）
├── lock.py              # OptimisticLock（locks 表 CAS）
├── idempotency.py       # IdempotencyStore（哈希去重 + TTL）
├── compensation.py      # CompensationExecutor（逆序 + 重试 + DLQ 上抛）
├── dlq.py               # DeadLetterQueue
├── wal.py               # TxActionLog（state.wal 薄包装 + 生命周期标记）
└── isolation.py         # 仅 IsolationSnapshot 抽象（可扩展点，不实现）
```

---

## 4. 数据模型

### 4.1 CheckpointStore 新增 3 张表

```sql
CREATE TABLE locks (
    resource_key TEXT PRIMARY KEY,
    version      INTEGER NOT NULL DEFAULT 0,
    owner_tx     TEXT NOT NULL,
    held_since   TIMESTAMP NOT NULL,
    expires_at   TIMESTAMP NOT NULL
);

CREATE TABLE idempotency_keys (
    idempotency_key TEXT PRIMARY KEY,   -- 必填；未显式传时 = sha256(签名)
    request_hash    TEXT NOT NULL,
    tx_id           TEXT,
    status          TEXT NOT NULL,      -- running | completed | failed
    result_json     TEXT,
    created_at      TIMESTAMP NOT NULL,
    expires_at      TIMESTAMP NOT NULL  -- now() + TTL(默认24h)
);

CREATE TABLE dead_letter (
    dlq_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id       TEXT NOT NULL,
    action_name TEXT NOT NULL,
    error       TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'open',  -- open | resolved
    created_at  TIMESTAMP NOT NULL,
    resolved_at TIMESTAMP
);
```

### 4.2 CheckpointStore 抽象新增 9 方法

锁（4）：`acquire_lock(resource_key, owner_tx, ttl)` / `compare_and_swap(resource_key, expected_version, owner_tx)` / `release_lock(resource_key, owner_tx)` / `read_version(resource_key)`

幂等（3）：`put_idempotency(record)` / `get_idempotency(key)` / `delete_expired_idempotency()`

DLQ（2）：`enqueue_dlq(entry)` / `list_dlq(limit, status)`

两后端（SQLAlchemy SQLite/PG 基类 + InMemory）同步实现。

### 4.3 WAL 生命周期

`WALActionType` 新增 `TX_BEGIN = "tx_begin"`、`TX_COMMIT = "tx_commit"`。动作日志为 `STATE_UPDATE` 且带 `tx_id`；事务首尾写 TX_BEGIN / TX_COMMIT 标记。

---

## 5. API 形态

```python
# --- 新代码（async 主路径）---
from agentorchestra.tx import TransactionCoordinator, TxAction, TxAbort

coord = TransactionCoordinator(store=checkpoint_store)
coord.register(TxAction("扣库存", execute_fn=deduct, compensate_fn=restock))
coord.register(TxAction("减余额", execute_fn=debit, compensate_fn=refund))

async with coord.transaction(
    idempotency_key="order-12345",   # 不传则自动 sha256 生成
    resources=["order:12345"],       # 乐观锁声明资源
    timeout=30.0,
) as tx:
    if not await tx.pre_condition("order:12345", expected_version=3):
        raise TxAbort("pre-condition failed")
    await tx.execute("扣库存", {"sku": "A1", "qty": 1})
    await tx.execute("减余额", {"uid": 7, "amount": 100})
# 退出无异常 → commit；异常 → 逆序补偿 → DLQ

# --- 旧同步 API（TransactionManager.execute 内部替换）---
mgr.execute([{"action": "扣库存", "params": {...}}, ...])
```

### 5.1 TransactionCoordinator

```python
class TransactionCoordinator:
    def __init__(self, store: CheckpointStore | None = None,
                 compensation_retries: int = 3,
                 compensation_backoff: float = 0.1,
                 idempotency_ttl: int = 86400,
                 lock_ttl: float = 30.0):
        ...

    def register(self, action: TxAction) -> None: ...
    def register_action(self, name, execute_fn, compensate_fn=None) -> TxAction: ...

    @asynccontextmanager
    async def transaction(self, idempotency_key=None, resources=None,
                          timeout=30.0) -> AsyncIterator[TxContext]:
        ...
```

### 5.2 TxAction / TxContext

```python
@dataclass
class TxAction:
    name: str
    execute_fn: Callable            # fn(params, tx_ctx) -> result
    compensate_fn: Callable | None  # fn(params, tx_ctx)
    idempotent: bool = True         # 重放安全标记

class TxContext:
    tx_id: str
    async def pre_condition(self, resource_key, expected_version=None) -> bool: ...
    async def execute(self, action_name: str, params: dict) -> dict: ...
    # commit/rollback 由 async with 隐式触发
```

### 5.3 异常与状态

- `TxAbort`: 用户主动中断（pre-condition 失败 / 规则拒绝），触发补偿，状态 `aborted`
- `TxConflict`: CAS 失败（乐观锁冲突），调用方决定重试
- `TxStatus`: `running / committed / aborted / compensation_failed`

### 5.4 sync 桥接（tx/sync.py）

```python
def run_sync(coro_factory):
    # 无运行中 loop → asyncio.run(coro_factory())
    # 已在 loop 内 → RuntimeError，提示调用方用 async with
```

`TransactionManager.execute()` 内部：构造/复用 coordinator（未配 store 则 in-memory），把 steps 依次 `execute`，等价旧 saga 语义但新增幂等/补偿/DLQ 能力。

---

## 6. 运行时数据流

```
enter:
  1. 幂等查重：key 已 completed → 直接返回首次结果（不执行）
  2. 生成 tx_id，幂等记 running
  3. resources 逐个 acquire_lock（version 快照）
  4. WAL: TX_BEGIN(tx_id)

execute(action, params):
  1. 校验 action 已注册
  2. action.execute_fn(params, tx_ctx) → result
  3. WAL: STATE_UPDATE(tx_id, {action, params, result})
  4. 记入 tx 已完成列表（供逆序补偿）

exit（无异常）:
  commit: 幂等标 completed + result；WAL TX_COMMIT；release all locks

exit（异常 / TxAbort）:
  compensate_reverse: 逆序遍历已完成 action
    - 每个 compensate_fn 重试 N 次（退避）
    - 耗尽 → DLQ.enqueue + 事务状态 compensation_failed
  幂等标 failed（若 key 存在）
  release all locks
```

---

## 7. 接入点

| 现有组件 | 接入方式 |
|---------|---------|
| `ontology/process/transaction.py:TransactionManager` | `register/register_action` 委托 coordinator；`execute()` 改用 sync 桥接 |
| `ontology/kinetic/action.py:ActionType` | 加 `idempotent: bool = True` 字段 |
| `ontology/storage/materialization.py` | `MaterializationTarget.write` 包 TxAction 工厂（`to_tx_action()`），本期提供但默认路径不改 |
| `state/backends/*` | 实现新增 9 方法 + 3 表建表 |
| `state/wal.py` | `WALActionType` 增 2 值 |

### 7.1 兼容约束

- `TransactionManager` 现有公开 API（register/register_action/execute/get_log/clear_log/savepoint/rollback_to）签名不变
- 未传 store → in-memory（现有 181 测试不落 DB）
- `TransactionManager.execute` 返回结构与旧版一致（`{"success", "completed", "failed", "compensated", "errors"}`）

---

## 8. 测试策略（tests/tx/）

| 文件 | 覆盖 |
|------|------|
| `test_coordinator.py` | 5-action 成功 commit + WAL 5 条 + TX_BEGIN/COMMIT |
| `test_compensation.py` | 第 3 个失败 → 逆序补偿 1、2 → success |
| `test_dlq.py` | 补偿失败 3 次 → DLQ open + 事务 compensation_failed |
| `test_idempotency.py` | 同 key 二次提交返回首次结果；TTL 过期重放 |
| `test_lock.py` | CAS 冲突 → TxConflict；version 递增；锁 TTL 释放 |
| `test_tm_integration.py` | 旧 `TransactionManager.execute` 兼容（含现有测试场景） |
| `test_wal_tx.py` | TX_BEGIN/COMMIT 标记 + tx_id 关联 |

复用 `tests/state/conftest.py` 的 sqlite/memory store fixtures。

验收：
- `pytest tests/tx/` 全绿
- `pytest tests/`（现有 224）全绿
- `ruff check agentorchestra/tx tests/tx`
- `mypy agentorchestra/tx`

---

## 9. 实施步骤

1. `state/wal.py`: WALActionType 增 2 值
2. `state/checkpoint.py`: CheckpointStore 抽象增 9 方法
3. `state/backends/sqlalchemy_base.py`: 3 表 + 9 方法实现
4. `state/backends/memory_backend.py`: 3 表 + 9 方法实现
5. 写 `tx/` 包：context → dlq → idempotency → lock → compensation → wal → coordinator → sync
6. 接入 `TransactionManager` / `ActionType.idempotent` / `MaterializationTarget.to_tx_action`
7. 写 `tests/tx/` 全套
8. 全量测试 + ruff + mypy
9. 提交

---

## 10. 风险与回退

- **旧 execute 测试破坏**：未传 store 用 in-memory 兜底；返回结构保持兼容
- **CheckpointStore 抽象膨胀**：9 个方法均带默认语义，子类不实现也可运行（抛 NotImplementedError 仅锁/幂等被用时触发）
- **补偿副作用**：execute_fn/compensate_fn 默认视为纯内存操作；需要持久化的补偿由调用方在其内部写 ObjectStore（WAL 已捕获）
- **并发冲突**：乐观锁冲突抛 TxConflict，调用方重试；不自动无限重试（roadmap P4 错误隔离）