# tx — 事务引擎运行时（P1 / M1）

把 `ontology/process/transaction.py` 的接口壳升级为真正的事务运行时：幂等键 + WAL + 逆序补偿 + DLQ + 乐观锁。

设计见 [M1 spec](../superpowers/specs/2026-09-03-m1-transaction-runtime-design.md)。

## 模块组成

| 文件 | 职责 |
|------|------|
| `coordinator.py` | `TransactionCoordinator`：async 事务核心（open/commit/rollback/补偿调度） |
| `context.py` | `TxAction` / `TxContext` / `TxAbort` / `TxConflict` / `TxReplay` / `TxStatus` |
| `sync.py` | `run_sync()`：同步桥接（供旧 `TransactionManager.execute`） |
| `lock.py` | `OptimisticLock`：基于 CheckpointStore.locks 表的 CAS 乐观锁 |
| `idempotency.py` | `IdempotencyStore`：幂等键哈希去重 + TTL（默认 24h） |
| `compensation.py` | `CompensationExecutor`：逆序补偿 + 重试 N 次 |
| `dlq.py` | `DeadLetterQueue`：补偿耗尽入死信 |
| `wal.py` | `TxActionLog`：复用 state.WAL（TX_BEGIN / STATE_UPDATE / TX_COMMIT 标记，tx_id 关联） |
| `isolation.py` | `IsolationSnapshot` 抽象（SSI 占位，M4 扩展点） |

## 快速开始（async 主路径）

```python
from agentorchestra.tx import TransactionCoordinator, TxAction, TxAbort

coord = TransactionCoordinator(store=checkpoint_store)
coord.register(TxAction("扣库存", execute_fn=deduct, compensate_fn=restock))
coord.register(TxAction("减余额", execute_fn=debit, compensate_fn=refund))

async with coord.transaction(
    idempotency_key="order-12345",   # 不传则自动 sha256 生成
    resources=["order:12345"],       # 乐观锁声明资源
    timeout=30.0,
    principal="alice", roles=["admin"],  # M3：事务身份
) as tx:
    if not await tx.pre_condition("order:12345", expected_version=3):
        raise TxAbort("pre-condition failed")
    await tx.execute("扣库存", {"sku": "A1", "qty": 1})
    await tx.execute("减余额", {"uid": 7, "amount": 100})
# 退出无异常 → commit；异常 → 逆序补偿 → DLQ
```

## 语义

| 行为 | 说明 |
|------|------|
| 幂等 | 同 `idempotency_key` 二次提交 → `TxReplay`（直接返回首次结果） |
| 补偿 | 动作失败 → 逆序补偿已完成动作；每动作重试 N 次（默认 3） |
| DLQ | 补偿耗尽 → `dead_letter` 表（open/resolved） |
| 乐观锁 | `locks` 表 version CAS；冲突 → `TxConflict` |
| WAL | 每动作写 `STATE_UPDATE`（带 tx_id）；首尾 TX_BEGIN/TX_COMMIT |

## 旧同步 API 兼容

`ontology/process/transaction.py:TransactionManager`：

```python
mgr = TransactionManager()                        # 纯 saga（内存，无 DB）
mgr.set_coordinator(TransactionCoordinator())     # 可选：启用 coordinator 引擎
mgr.register("deduct", action_fn, compensate_fn)
r = mgr.execute([{"action": "deduct", "params": {...}}])
# r: {"success", "failed", "compensated", "errors", "engine": "coordinator"|None}
```

默认（无 coordinator）行为不变；有 coordinator 时 `execute` 经 `run_sync` 桥接新运行时。

## SLO 指标（M5）

coordinator commit/rollback 自动发指标（`observability/metrics.py`，默认 NoOp）：
`tx_duration_seconds` / `tx_rollback_total` / `tx_compensation_triggered_total`。
