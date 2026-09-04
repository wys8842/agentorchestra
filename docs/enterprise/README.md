# 企业级就绪（P0–P6）总览

Symphony 从"Demo 框架"到"可生产多 Agent 平台"的实施落地。逐里程碑交付，每个自带 spec + 验收 + 向后兼容。

> 关联路线图：[enterprise-readiness-roadmap](../superpowers/specs/2026-09-03-enterprise-readiness-roadmap.md)

## 里程碑

| 里程碑 | 主题 | 新包 | Spec | 状态 |
|--------|------|------|------|------|
| M0 / P0 | 持久化与恢复 | `state/` | [spec](../superpowers/specs/2026-09-03-m0-persistence-design.md) | ✅ |
| M1 / P1 | 事务引擎运行时 | `tx/` | [spec](../superpowers/specs/2026-09-03-m1-transaction-runtime-design.md) | ✅ |
| M2 / P2 | Agent 通信升到图/DAG | `orchestration/` | [spec](../superpowers/specs/2026-09-04-m2-agent-graph-design.md) | ✅ |
| M3 / P3 | 对象身份与权限落地 | `governance/` | [spec](../superpowers/specs/2026-09-04-m3-object-identity-acl-design.md) | ✅ |
| M4 / P4 | 并发模型收敛 | （core 改造） | [spec](../superpowers/specs/2026-09-04-m4-concurrency-convergence-design.md) | ✅ |
| M5 / P5 | 可观测性对齐企业 | `observability/`（增强） | [spec](../superpowers/specs/2026-09-04-m5-observability-design.md) | ✅ |
| M6 / P6 | 多租户隔离 | `tenancy/` | [spec](../superpowers/specs/2026-09-04-m6-multitenancy-design.md) | ✅ |

模块文档：[state](../state/README.md) · [tx](../tx/README.md) · [orchestration](../orchestration/README.md) · [governance](../governance/README.md) · [tenancy](../tenancy/README.md) · [observability](../observability/README.md)

## 设计原则

1. **自研优先**：不引入 LangGraph / Temporal；新依赖仅允许基础件（SQLAlchemy/asyncpg）。M5 后为**零依赖**自研 exporters。
2. **WAL 是命脉**：所有状态变更先写 append-only 日志（`state.wal`），再应用到内存。
3. **乐观并发**：业务对象带 `version`；事务提交前 CAS 比对（`ObjectCAS` / `locks` 表）。
4. **错误隔离**：单事务失败不污染其他事务；补偿失败进 DLQ，不无限重试。
5. **横切关注**：可观测性、安全、多租户作为横切层，不混入业务模块。

## 维度对照

| 维度 | 起点 | 终点 |
|------|------|------|
| 持久化 | 内存 / JSONL | WAL + Checkpoint + 周期快照（SQLite 默认 / PG 生产） |
| 事务引擎 | 接口壳 | 可恢复 + 幂等 + 逆序补偿 + DLQ + 乐观锁 |
| Agent 通信 | 父子 tool | DAG + Inbox + 投递回执 + 有界回环 |
| 对象身份 | 无版本 | version / created_tx / last_modified_tx + RBAC/ACL + WORM 审计 |
| 并发模型 | sync + 临时 asyncio | async 主路径 + 并发信号量收敛 |
| 可观测性 | 本地 JSONL/HTML | Prometheus 文本指标 + 可选 OTLP trace（零依赖） |
| 多租户 | 无 | tenant_id + namespace 隔离 + token 配额 + 用量导出 |

## 集成用法速览

```python
# P0 持久化 + P1 事务：Agent checkpoint 恢复
from agentorchestra.state import get_default_store, ThreadManager
store = get_default_store()                    # SQLite 零配置
cp = await ThreadManager(store).latest_checkpoint("order-1")

# P1 事务 + P3 权限 + M5 指标
from agentorchestra.tx import TransactionCoordinator
coord = TransactionCoordinator(store=store, permission_checker=checker)
async with coord.transaction(principal="alice", roles=["admin"],
                             idempotency_key="order-1") as tx:
    tx.authorize("Order", "write", obj_id="o1")
    await tx.execute("扣库存", {"qty": 1})

# P2 图通信
from agentorchestra.orchestration import Graph, AgentNode
g = Graph(store=store)
g.add_node("coder", AgentNode(agent_factory=coder_factory))
await g.run({"task": "..."}, thread_id="t1")

# P6 多租户 + 配额
from agentorchestra.tenancy import TenantManager
with TenantManager().sync_run_as("acme", "alice"):
    ...   # memory/LLM 自动按租户隔离/计费
```

## 后续（roadmap 标为可选 / P7）

- M5 OTLP exporter 完整企业部署（当前默认关）
- P7 硬隔离（独立进程多租户）
- DB 级 WORM trigger（当前接口层保证）
- session_store / ontology storage 全面 async 化
