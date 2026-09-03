# 企业级就绪路线图 — 从「Demo 框架」到「可生产多 Agent 平台」

- Status: Draft
- Date: 2026-09-03
- 关联诊断: 用户提供的 4 个底座缺陷（持久化、多 Agent 通信、事务引擎、并发治理）

---

## 1. 路线概览

### 1.1 设计原则

| 原则 | 含义 |
|------|------|
| **P1. 自研优先** | 优先自研实现，避免引入 LangGraph / Temporal 等重量级框架；新依赖只允许 PG / Redis / SQLite 等基础件 |
| **P2. WAL 是命脉** | 所有状态变更先写 append-only 日志，再应用到内存；崩溃后按日志重放/补偿 |
| **P3. 乐观并发** | 业务对象一律带 `version`；事务提交前做 CAS 比对；冲突重试由调用方决定 |
| **P4. 错误隔离** | 单个事务失败不得污染其他事务；补偿失败进入 dead-letter，不无限重试 |
| **P5. 横切关注** | 可观测性、安全、多租户作为横切层，不混入业务模块 |

### 1.2 路线图

```
P0 持久化与恢复 ─┐
                ├─► P1 事务引擎从接口变运行时 ─┐
                │                            ├─► P2 Agent 通信升到图/DAG
                │                            │       │
                │                            └───────┴─► P3 对象身份与权限落地
                │
                └─► P5 可观测性对齐企业（横切，与 P0 并行启动）
P4 并发模型定型（最后收敛）
P6 多租户隔离（依赖 P3 权限 + P5 审计）
```

依赖关系：
- **P0 是地基**：所有写状态都要先能持久化
- **P1 依赖 P0**：事务引擎的对象图 WAL 复用 P0 的存储
- **P2 依赖 P0 + P1**：消息状态、补偿动作需要持久化和事务保护
- **P3 依赖 P1**：权限决策在事务 pre-condition 阶段生效
- **P4 收敛于最后**：所有上层路径定型后，统一异步化
- **P5 与 P0 并行启动**：横切关注
- **P6 在 P3 之后**：权限 + 审计稳定后再加租户隔离

### 1.3 风险总览

| 风险 | 缓解 |
|------|------|
| 自研事务引擎复杂度高 | 收敛到最小可用集（无分布式锁、单机版起步），不抢 Temporal 的能力 |
| 持久化层重构破坏现有 API | 旧 `MemoryStore`/`SessionStore`/`Ontology Store` 保留为兼容层，新接口并入 `agentorchestra.state` |
| Agent 通信层推翻现有 TaskTool | 保留 `TaskTool`，新通信层只加新工具 + 新组合原语 |
| 性能回退（持久化带来的 I/O） | 写路径用 WAL 批量合并；读路径加内存缓存；提供"开发模式"绕过持久化 |

---

## 2. P0 — 持久化与恢复

### 2.1 目标

把框架的"内存上下文"升级为 **durable checkpoint**。Agent 跑崩 / Pod 被 kill 后能从断点恢复；Ontology 事务做到崩溃可补偿。

### 2.2 关键决策

| 决策项 | 结论 | 理由 |
|--------|------|------|
| 状态后端 | **PG（首选）/ SQLite（单机降级）** | 成熟可靠；PG 支持行级锁 + WAL；SQLite 兼容单机/Edge 场景 |
| 客户端 | **SQLAlchemy 2.0 + asyncpg** | 唯一接受的"重型依赖"（仅 ORM 与异步驱动，不引入完整框架） |
| Checkpoint 格式 | **append-only WAL + 周期快照** | 恢复快（WAL replay）+ 存储省（快照压缩历史） |
| 索引粒度 | **`{thread_id, checkpoint_id}`** 与 LangGraph 对齐 | 兼容未来与 LangGraph 互操作的可能性 |
| HITL | **`interrupt(resume_token)` 协议** | Agent 主动发起中断，存 token，业务侧 resume 时注入 |

### 2.3 模块设计

```
agentorchestra/state/                  # 新顶层包
├── __init__.py
├── checkpoint.py      # Checkpoint / CheckpointStore 抽象 + PG/SQLite 实现
├── thread.py          # ThreadState / ThreadManager（一个 thread 一个会话）
├── wal.py             # append-only 日志（预写后应用）
├── interrupt.py       # HITL 中断与恢复
└── snapshot.py        # 周期快照 / 压缩
```

### 2.4 接入点

| 现有组件 | 接入方式 |
|----------|----------|
| `Agent.run()` | 每步 `_save_checkpoint(thread_id, state)` 同步刷盘 |
| `Agent.arun()` | 异步 checkpoint 写入（不阻塞主流程） |
| `OntologyEngine` | 所有 `MaterializationManager.register_target` 触发的对象变更走 WAL |
| `MemoryStore` | 现有 `SqliteBackend` 复用 PG/SQLite 实现，作为统一底层 |

### 2.5 验收标准

- Agent 中途 kill，resume `后能从最近一次 LLM 响应继续
- Ontology 事务中途失败，恢复后未补偿的动作自动补偿
- 单事务平均写延迟 < 5ms（PG 本机）/ 50ms（远程）

---

## 3. P1 — 事务引擎从接口变运行时

### 3.1 目标

把 `ontology/process/transaction.py` 中的 `TransactionManager.register/execute` 从"接口壳"变为真正的**事务运行时**：分布式锁、幂等键、WAL、两阶段补偿、dead-letter。

### 3.2 关键决策

| 决策项 | 结论 | 理由 |
|--------|------|------|
| 协调器 | **自研 `TransactionCoordinator`** | 控制在框架内，避免 Temporal SDK 体积 |
| 锁模型 | **乐观锁（version 比对）+ 必要时降级悲观** | 简单业务用乐观，冲突再升级 |
| 隔离级别 | **Serializable Snapshot Isolation（SSI）** | 防止幻读与写偏序 |
| 幂等键 | **`idempotency_key` 字段必填，TTL 24h** | 防重放、兼容外部 HTTP 回调 |
| 补偿策略 | **逆序 compensate + 重试 N 次 + DLQ** | 补偿失败不无限循环 |
| 死信 | **`dead_letter` 表 + 监控告警** | 人工介入 |

### 3.3 模块设计

```
agentorchestra/tx/                          # 新顶层包
├── __init__.py
├── coordinator.py         # TransactionCoordinator：开/关事务、补偿调度
├── lock.py                # OptimisticLock（version 比对）+ 升级悲观锁
├── idempotency.py         # IdempotencyStore（24h TTL 哈希去重）
├── wal.py                 # TxActionLog：append-only 动作日志
├── compensation.py        # 补偿编排：逆序 + 重试 + DLQ
├── isolation.py           # SSI 快照
└── dlq.py                 # DeadLetterQueue
```

### 3.4 API 形态

```python
async with coordinator.transaction(
    idempotency_key="order-12345",
    timeout=30.0,
) as tx:
    # pre-condition：基于 tx 视角的对象快照
    if not await tx.pre_condition(order):
        raise TxAbort("pre-condition failed")
    result = await tx.execute(action_a, args_a)
    # post-condition 校验 + 写 WAL
    await tx.execute(action_b, args_b)
# commit：快照所有变更
# 失败自动逆序补偿
```

### 3.5 接入点

| 现有组件 | 接入方式 |
|----------|----------|
| `TransactionManager.execute(steps)` | 内部替换为 `coordinator.transaction(...)` 上下文 |
| `Action.execute()` | 加 `idempotent: bool` 字段；Coordinator 据此决定重放安全 |
| Ontology 物化 | 物化动作包成 TxAction 走事务引擎 |

### 3.6 验收标准

- 单事务内 5 个 action 全部成功 → commit，WAL 留 5 条记录
- 第 3 个 action 抛异常 → 自动 compensate 1、2，进入成功态
- compensate 连续失败 3 次 → 进 DLQ，事务标记 `compensation_failed`
- 同 idempotency_key 二次提交 → 直接返回首次结果

---

## 4. P2 — Agent 通信升到图/DAG

### 4.1 目标

把"子 Agent 是父 Agent 的 tool"升格为**对等节点图**：Agent 节点 + 消息 Inbox + 投递回执 + 条件边。允许复杂协作（"审批驳回→风控重算→客户经理通知"）。

### 4.2 关键决策

| 决策项 | 结论 | 理由 |
|--------|------|------|
| 拓扑 | **DAG（节点 = Agent，边 = 消息条件）** | 支持条件分支与并行，无需 cycle |
| 消息层 | **自研 `Inbox`（持久化队列 + 投递回执）** | 与 P1 事务引擎复用 WAL |
| 节点类型 | `AgentNode` / `RouterNode`（条件路由） / `MergeNode`（多流汇聚） | 三类节点覆盖常见模式 |
| 现有 TaskTool | **保留为简单场景工具**；新通信层走 `Graph`/`Inbox` | 不打破向后兼容 |
| 调度 | **异步队列 + 图执行器** | 与 P4 并发模型一致 |
| 触发 | **节点间消息 + 显式依赖边** | 显式声明依赖，避免循环触发 |

### 4.3 模块设计

```
agentorchestra/orchestration/                    # 新顶层包
├── __init__.py
├── graph.py               # Graph / Node / Edge 声明式
├── inbox.py               # Inbox：持久化消息队列 + 投递回执 + 重试
├── nodes.py               # AgentNode / RouterNode / MergeNode
├── scheduler.py           # 拓扑调度（DAG 拓扑排序 + 异步派发）
├── delivery.py            # 投递回执、超时、背压
└── migration.py           # 从 TaskTool 迁移指南
```

### 4.4 API 形态

```python
graph = Graph()
graph.add_node("coder", AgentNode(agent_factory=coder_factory))
graph.add_node("reviewer", AgentNode(agent_factory=reviewer_factory))
graph.add_node("tester", AgentNode(agent_factory=tester_factory))

graph.add_edge("coder", "reviewer", when="all_done")
graph.add_edge("reviewer", "coder", when="rejected")  # 驳回循环回写
graph.add_edge("reviewer", "tester", when="approved")

result = await graph.run(initial_message, thread_id="order-12345")
```

### 4.5 验收标准

- 3 节点图按依赖顺序执行；条件边正确路由
- 节点异常自动触发依赖回退或告警
- Inbox 消息 7 天可回溯；投递回执明确
- 老 `TaskTool` 代码无修改仍能工作

---

## 5. P3 — 对象身份与权限落地

### 5.1 目标

Ontology 对象带版本号与事务身份；权限基于"事务携带 principal + 对象 ACL 在 pre-condition 求值"；审计日志走 WORM 存储。

### 5.2 关键决策

| 决策项 | 结论 | 理由 |
|--------|------|------|
| 对象身份 | 每对象带 `version`, `created_tx`, `last_modified_tx` | 乐观锁与审计基础 |
| 权限模型 | **RBAC + 对象 ACL（行级）** | 既满足角色，又支持细粒度 |
| 决策时机 | **pre-condition 内求值** | 与事务引擎集成，权限与动作原子 |
| 审计存储 | **WORM 表（append-only，禁 update/delete）** | 合规要求 |
| Principal 携带 | **事务上下文（ThreadLocal/ContextVar）** | 与 P1 协调器对齐 |

### 5.3 模块设计

```
agentorchestra/governance/             # 新包（在现有 ontology/governance 基础上扩展）
├── identity.py             # IdentityService：principal + roles 上下文
├── acl.py                  # ACL：对象级 + 角色级
├── audit.py                # AuditLog：WORM 写入
└── cas.py                  # CAS：version 比对
```

### 5.4 接入点

- `ObjectStore.register_object_type()` 内自动加 `version`/`created_tx` 列
- `Action.execute()` pre-condition 检查 `acl + principal`
- `coordinator.transaction()` 注入 `principal` 到 ctx
- 审计日志由 `TransactionCoordinator` 自动记录所有对象变更

### 5.5 验收标准

- 并发事务同时改同对象 → 仅一个 commit，另一个抛 CAS 冲突
- 无权用户尝试修改 → pre-condition 抛 `PermissionDenied`，事务自动回滚
- 审计表禁 update/delete（DB 层 grant 控制）

---

## 6. P4 — 并发模型定型

### 6.1 目标

全链路统一为 **asyncio 异步模型**；Ontology 写路径禁止内存 dict 共享，全部走持久化层单写者或行锁。

### 6.2 关键决策

| 决策项 | 结论 | 理由 |
|--------|------|------|
| 主并发模型 | **asyncio + asyncpg/SQLAlchemy async** | Python 标准、生态成熟 |
| 同步 API | **薄包装**：自动 `_run_sync(coro)` 给不愿 async 的调用方 | 不破坏旧 API |
| Ontology 写路径 | **禁止内存 dict 共享**；全部走 P0+P1 的持久化层 | 满足 P0 的崩溃恢复假设 |
| 子 Agent 并发 | **已有 `asyncio.gather` + semaphore**，补 `max_concurrent_subagents` 配置 | 复用现成机制 |
| LLM 并发 | **已有 `run_in_executor`**；改造为纯 asyncio | 减少线程切换 |

### 6.3 模块设计

- 不新增模块，主要做"改造与收敛"：
  - `core/agent.py` 的 `arun` 已是 asyncio，强化为主路径
  - `core/session_store.py` 改造为 async 优先
  - `ontology/storage/` 异步接口扩展
  - `tools/registry.py` `async_execute_tool` 成为默认

### 6.4 验收标准

- 跑现有 182 个测试，全部通过（向后兼容）
- 单个 Agent 跑 1000 次并发 LLM 调用，p99 延迟 < 1s（模拟）
- 同步 `run()` 与异步 `arun()` 在所有 Agent 行为一致

---

## 7. P5 — 可观测性对齐企业

### 7.1 目标

TraceLogger 不止本进程 JSONL/HTML；接 **OTel 标准**，span 与事务 id、对象 id、action id 绑定；产出"补偿触发率""事务回滚率"等 SLO 指标。

### 7.2 关键决策

| 决策项 | 结论 | 理由 |
|--------|------|------|
| 协议 | **OpenTelemetry（OTLP）** | 行业标准，企业有现成后端 |
| SDK | **opentelemetry-python（OTel 官方）** | 唯一接受的"重型依赖"（仅 SDK） |
| Span 关联 | `trace_id` + `tx_id` + `obj_id` + `action_id` 多维属性 | 与 P1/P3 事务体系打通 |
| SLO 指标 | 补偿触发率、回滚率、平均事务时长、Agent 召回命中率 | 业务可观测 |
| 兼容 | 保留现有 JSONL/HTML 作为开发态默认输出 | 不破坏本地调试体验 |

### 7.3 模块设计

```
agentorchestra/observability/        # 扩展现有包
├── trace_logger.py          # 现有，扩展 OTLP exporter
├── otel_exporter.py         # 新增：OTLP exporter
├── metrics.py               # 新增：Prometheus/OTel metrics
└── slo.py                   # 新增：业务 SLO 指标定义
```

### 7.4 接入点

- `TraceLogger` 增加 `exporter="console|jsonl|otlp"` 配置
- `TransactionCoordinator` 在 commit/rollback 时发指标
- `Agent.run()` 在每步 start/end 时发 span

### 7.5 验收标准

- 配置 `otel_exporter=otlp` 后，trace 进入企业后端（如 Jaeger/Tempo）
- 指标如 `tx_rollback_rate` 可在 Grafana 配 dashboard
- 开发模式（默认）仍输出 JSONL/HTML

---

## 8. P6 — 多租户隔离

### 8.1 目标

多个业务团队/客户共享同一部署时，资源、对象、记忆、Agent 调用按租户隔离；配额与计费可独立计量。

### 8.2 关键决策

| 决策项 | 结论 | 理由 |
|--------|------|------|
| 隔离粒度 | **tenant_id（**粗粒度**）+ namespace（细粒度）** | 复用 v1.1 memory namespace，租户做顶层边界 |
| 资源隔离 | **软隔离（配额 + 限流）**起步，硬隔离（独立进程）留 P7 | 降低运营复杂度 |
| 配额维度 | token LLM / 单价 / 并发 Agent 数 / 存储 | 覆盖常见计费 |
| 数据隔离 | **每个租户独立 namespace + 独立 schema 命名空间** | 复用 P3 ACL |
| 计费 | 配额触发软限；超额硬限（可选） | 标准 SaaS 模式 |

### 8.3 模块设计

```
agentorchestra/tenancy/              # 新包
├── __init__.py
├── tenant.py              # Tenant / TenantContext
├── quota.py               # 配额管理（token/并发/存储）
├── isolation.py           # 隔离上下文（注入 namespace + schema）
└── billing.py             # 用量统计与导出
```

### 8.4 接入点

- `MemoryManager` 默认 namespace = `f"{tenant_id}:{user_id}"`
- `TransactionCoordinator` 注入 tenant context，所有审计带带 tenant 标签
- LLM 调用在 token 配额维度计数

### 8.5 验收标准

- 两个租户跑相同 agent namespace 完全隔离
- 配额耗尽时事务优雅失败（不崩进程）
- 用量统计可导出 CSV/JSON 给计费系统

---

## 9. 实施顺序与里程碑

按依赖关系串行，每个里程碑自带验收：

```
M0 (1-2 周) ──► M1 (2-3 周) ──► M2 (2-3 周) ──► M3 (1-2 周) ──► M4 (1 周) ──► M5 并行 (贯穿) ──► M6 (1-2 周)
```

| 里程碑 | 范围 | 验收 |
|--------|------|------|
| M0 | P0 持久化层：`state/checkpoint.py` + `state/wal.py` + PG/SQLite 实现 + Agent/Ontology 接入 | Agent resume + Ontology crash-recover |
| M1 | P1 事务引擎：`tx/coordinator.py` + `tx/wal.py` + 接入 `TransactionManager` | 5-action 事务、补偿、DLQ |
| M2 | P2 Agent 通信：`orchestration/graph.py` + `inbox.py` + 3 类节点 | 3 节点 DAG 端到端 |
| M3 | P3 权限：`governance/identity.py` + `governance/acl.py` + Ontology 接入 | CAS 冲突、PermissionDenied |
| M4 | P4 并发：async 化与收敛 | 182 测试通过 + 并发压测 |
| M5 | P5 可观测性：OTel 接入（与 M0-M4 并行） | OTLP trace + SLO 指标 |
| M6 | P6 多租户：tenant context + 配额 | 两租户隔离 + 用量导出 |

### 9.1 跨里程碑依赖

```
M0 ──► M1 ──► M2 ──► M3 ──► M4
                         │
                         └─► M6（多租户需要权限 + 审计）
M5（横切，可与 M0-M6 并行）
```

---

## 10. 总结

| 维度 | 现状 | 路线终点 |
|------|------|----------|
| 持久化 | 内存 / JSONL | **PG WAL + 周期快照** |
| 事务引擎 | 接口壳 | **可恢复 + 幂等 + 补偿 + DLQ** |
| Agent 通信 | 父子 tool | **DAG + Inbox + 投递回执** |
| 对象身份 | 无版本 | **乐观锁 + ACL + WORM 审计** |
| 并发模型 | sync + 临时 asyncio | **统一 asyncio + 单写者** |
| 可观测性 | 本地 JSONL/HTML | **OTel OTLP + 业务 SLO** |
| 多租户 | 无 | **tenant_id + 配额 + 用量导出** |

### 10.1 原则重申

1. **自研优先**：不引入 LangGraph / Temporal；唯一接受的"重型依赖"是 SQLAlchemy/asyncpg（持久化）、OpenTelemetry SDK（可观测性）
2. **WAL 是命脉**：所有状态变更必须先落日志
3. **乐观并发 + 必要时悲观**：避免锁风暴
4. **错误隔离**：事务失败不污染其他事务
5. **横切关注**：可观测性、安全、多租户不混入业务模块

### 10.2 实施风险与回退

- 每个里程碑都是独立 PR；任一阶段未达验收可暂停
- P0 是地基，如未达验收，后续全停
- P5 与其他里程碑并行启动，但不强依赖验收（即使未达也不阻塞主线）