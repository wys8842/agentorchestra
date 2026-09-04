# M4 — 并发模型收敛（P4）设计

- Status: Approved
- Date: 2026-09-04
- Milestone: M4 / P4（路线图 §6）
- 依赖: M0-M3
- 关联路线图: `docs/superpowers/specs/2026-09-03-enterprise-readiness-roadmap.md`

---

## 1. 目标与范围

并发模型收敛：async 主路径验证 + 子 Agent/工具并发上限。roadmap §6.4 验收：
- 同步 `run()` 与异步 `arun()` 行为一致
- 并发压测受控（信号量限流，不失控）

**不在范围**（后续长期工程）：
- session_store.py / ontology/storage/backends 全面 async 化
- LLM 底层改纯 asyncio（改 adapter）

---

## 2. 关键决策

| 决策项 | 结论 |
|--------|------|
| 范围 | 收敛点：并发上限 + async 主路径验证 |
| 子 Agent 并发 | `Config.max_concurrent_subagents`（默认 2）；`run_as_subagent` 异步并发受限流 |
| 工具并发 | 复用现有 `max_concurrent_tools`（默认 3）已有机制 |
| LLM | `ainvoke` 已 async 主路径（保持）；并发压测验证 |

---

## 3. 接入

| 组件 | 改动 |
|------|------|
| `core/config.py` | `max_concurrent_subagents: int = 2` |
| `core/agent.py` | `_subagent_semaphore` 按 config 懒建；`arun_stream`/并发子代理受控 |
| tests | `tests/concurrency/` 新增：sync/async 一致性 + 并发上限 |

---

## 4. 数据流

```
Config(max_concurrent_subagents=2)
Agent._subagent_semaphore = asyncio.Semaphore(2)
async def _run_subagents_concurrently(tasks):
    async with semaphore: await task  # 同一时刻 ≤2 个子代理
```

---

## 5. 测试策略（tests/concurrency/）

| 文件 | 覆盖 |
|------|------|
| `test_agent_concurrency.py` | max_concurrent_subagents=2 → 并发峰值 ≤2 |
| `test_sync_async_parity.py` | sync run / async arun 对简单 Agent 输出一致 |

兼容：现有 310 测试全绿。

---

## 6. 验收标准

- [ ] `pytest tests/concurrency/` 全绿
- [ ] `pytest tests/`（现有 310）全绿
- [ ] ruff + mypy

---

## 7. 实施步骤

1. Config 加 `max_concurrent_subagents`
2. Agent 加信号量 + 并发执行入口
3. tests/concurrency/
4. 全量回归 + lint + mypy
5. 提交