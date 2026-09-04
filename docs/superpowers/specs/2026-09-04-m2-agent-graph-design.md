# M2 — Agent 通信升到图/DAG（P2）设计

- Status: Approved
- Date: 2026-09-04
- Milestone: M2 / P2（路线图 §4）
- 依赖: M0（`agentorchestra.state` CheckpointStore / WAL）、M1（事务运行时，可选接入）
- 关联路线图: `docs/superpowers/specs/2026-09-03-enterprise-readiness-roadmap.md`

---

## 1. 目标与范围

把"子 Agent 是父 Agent 的 tool"升格为**对等节点图**：Agent 节点 + 消息 Inbox + 投递回执 + 条件边。允许复杂协作（"审批驳回→风控重算→客户经理通知"）。

**M2 验收（roadmap §4.5）**：

- [ ] 3 节点图按依赖顺序执行；条件边正确路由
- [ ] 节点异常自动触发依赖回退或告警
- [ ] Inbox 消息 7 天可回溯；投递回执明确
- [ ] 老 TaskTool 代码无修改仍能工作

**不在本里程碑范围**：

- M4 全链路 async 化收敛
- M6 多租户隔离
- 图执行的消息产物通过 M1 coordinator 完整事务包裹（本期消息落表；tx 包裹留后续）

---

## 2. 关键决策（用户确认）

| 决策项 | 结论 |
|--------|------|
| Inbox 存储 | 复用 CheckpointStore（加 `inbox_messages` + `inbox_acks` 表） |
| 拓扑 | DAG + 有界回环（`max_iterations=3`，防 reviewer→coder 无限循环） |
| AgentNode 调用 | async 核心；节点内 `arun()`（无 arun 则 `run_in_executor(run)`） |
| 消息保留 | TTL 7 天（懒清理） |
| 投递重试 | 指数退避，最多 5 次；耗尽 → failed + `on_delivery_failed` 回调 |
| 异常 | `on_node_error` 钩子 + 有界回环耗尽 → 降级告警 |
| 无条件边 | 未标注 `when` 的边 = 无条件（总是激活） |
| tx 包裹 | 本期不引入（消息直接落 inbox 表，非 coordinator 事务包裹） |

---

## 3. 包结构

```
agentorchestra/orchestration/
├── __init__.py            # 公共 API
├── graph.py               # Graph / Node / Edge 声明式 + 拓扑校验（含有界回环计数）
├── nodes.py               # AgentNode / RouterNode / MergeNode
├── scheduler.py           # 图执行器（拓扑排序 + async 派发 + 条件路由 + 回环计数）
├── inbox.py               # Inbox（持久化队列 + 回执 + 重试）
├── delivery.py            # 投递回执/超时/指数退避
├── events.py              # NodeEvent / DeliveryEvent（供 trace 与回调）
└── migration.py           # TaskTool→Graph 迁移 helper + 指南
```

---

## 4. 数据模型

### 4.1 CheckpointStore 新增 2 张表

```sql
CREATE TABLE inbox_messages (
    msg_id       TEXT PRIMARY KEY,
    graph_id     TEXT NOT NULL,
    thread_id    TEXT NOT NULL,
    from_node    TEXT,
    to_node      TEXT NOT NULL,
    content_json TEXT NOT NULL,
    condition    TEXT,                -- 条件边标签（approved/rejected/done）
    status       TEXT NOT NULL,       -- queued | delivered | failed | expired | acked
    attempts     INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMP NOT NULL,
    expires_at   TIMESTAMP NOT NULL,  -- created_at + 7d
    delivered_at TIMESTAMP,
    ack_token    TEXT
);

CREATE TABLE inbox_acks (
    msg_id    TEXT PRIMARY KEY,
    ack_token TEXT,
    acked_at  TIMESTAMP,
    status    TEXT NOT NULL           -- acked | rejected
);
```

### 4.2 CheckpointStore 抽象新增 6 方法

- `enqueue_message(msg: InboxMessage) -> None`
- `list_pending_messages(thread_id, to_node=None, limit=100) -> List[InboxMessage]`
- `mark_delivered(msg_id, delivered_at=None) -> None`
- `mark_failed(msg_id, error, attempts) -> None`
- `ack_message(msg_id, ack_token, status="acked") -> None`
- `delete_expired_messages() -> int`

两后端（SQLAlchemy 基类 + InMemory）同步实现。

---

## 5. 模块接口

### 5.1 graph.py

```python
class Edge:
    source: str; target: str
    when: Optional[str]      # None = 无条件

class Node(ABC):
    name: str
    async def run(self, message: dict, ctx: NodeContext) -> NodeOutput: ...

class Graph:
    def __init__(self, store=None, max_iterations: int = 3): ...
    def add_node(self, name: str, node: Node) -> None: ...
    def add_edge(self, source: str, target: str, when: str | None = None) -> None: ...
    def validate(self) -> list[str]: ...   # 返回拓扑/未知节点等错误
    async def run(self, initial_message: dict, thread_id: str, ...) -> GraphResult: ...
```

### 5.2 nodes.py

```python
class AgentNode(Node):
    def __init__(self, name, agent_factory: Callable[[str], Agent]): ...
    async def run(self, message, ctx):        # arun, fallback run_in_executor(run)
        ...

class RouterNode(Node):
    def __init__(self, name, route_fn: Callable[[dict, NodeContext], str]): ...
    # 返回 when 标签；无匹配边 → drop

class MergeNode(Node):
    # 汇聚多上游：等所有入边消息齐后合并输出单条
```

### 5.3 scheduler.py

```python
class GraphScheduler:
    async def execute(self, graph, initial_message, thread_id,
                      on_node_error=None, on_delivery_failed=None) -> GraphResult: ...
```

### 5.4 inbox.py / delivery.py

```python
class Inbox:
    def __init__(self, store): ...
    async def send(self, graph_id, thread_id, from_node, to_node,
                   content, condition=None, ttl_seconds=604800) -> str: ...
    async def poll(self, thread_id, to_node=None) -> list[InboxMessage]: ...
    async def ack(self, msg_id, ack_token, status="acked") -> None: ...

class DeliveryManager:
    async def deliver(self, msg) -> None:      # 指数退避重试 ≤5
    async def retry(self, msg, on_failed=None) -> None: ...
```

---

## 6. 运行时数据流

```
graph.run(initial_message, thread_id)
  1. validate()：DAG + 未知节点 + 回边合法性
  2. 入队首个消息（enqueue_message → status=queued）
  3. scheduler 循环：
       poll 该 thread 的 queued 消息
       按消息 to_node 派发：delivery.deliver(msg)（回执 ack）
       节点执行 node.run(message) → NodeOutput
       NodeOutput 携带 result + route 标签
       依条件边找下游：when 匹配才激活；无条件边总是激活
       下游消息 enqueue（记录 from/to/condition）
       有界回环：目标节点 iteration++（ctx 记录）；达 max → 不派发 + 告警
  4. 终止：无 pending 消息 或 iteration 耗尽 → GraphResult
```

**执行记录**：每次消息入队/投递/回执/ack 落 inbox 表 → 7 天可回溯；`delivery.py` 对失败消息指数退避重试 ≤5 次。

---

## 7. 迁移（migration.py）

- `TaskToolGraphAdapter`：把 TaskTool 兼容的 `agent_factory` 包成 `AgentNode`（`name` → `Agent(name)`）。
- 文档式指南 docstring：何时用 TaskTool（简单一次性子任务）vs Graph（协作/条件/回环）。

---

## 8. 测试策略（tests/orchestration/）

| 文件 | 覆盖 |
|------|------|
| `test_graph.py` | 声明 / 拓扑校验 / 非法边（未知节点/自环）拒绝 |
| `test_scheduler.py` | 3 节点按依赖顺序执行；条件边 approved/rejected 路由 |
| `test_bounded_loop.py` | reviewer→coder rejected 回环达 3 次转告警（不无限循环） |
| `test_nodes.py` | AgentNode（arun / fallback run）/ RouterNode / MergeNode |
| `test_inbox.py` | 消息持久化 / TTL 过期清理 / ack 回执 |
| `test_delivery.py` | 指数退避重试 5 次 + failed + `on_delivery_failed` |
| `test_error_handling.py` | 节点异常触发 `on_node_error` + 依赖回退 |
| `test_tasktool_compat.py` | TaskTool 原测试通过 + GraphAdapter 不破坏 |

辅助：`tests/orchestration/conftest.py` 复用 sqlite/memory store fixtures + 假 Agent 工厂（记录调用、可配置抛错）。

**兼容保证**：不改 `tools/builtin/task_tool.py`；`tests/test_builtin_tools.py::TestTaskTool` 必须继续通过。

---

## 9. 验收标准

- [ ] `pytest tests/orchestration/` 全绿
- [ ] `pytest tests/`（现有 247）全绿
- [ ] `ruff check agentorchestra/orchestration tests/orchestration`
- [ ] `mypy agentorchestra/orchestration`
- [ ] TaskTool 原测试通过（未改 task_tool.py）
- [ ] Inbox 7 天可回溯（测试用短 TTL 模拟）+ 投递回执明确

---

## 10. 实施步骤

1. `state/records.py` 加 `InboxMessage` / `InboxAck` dataclass
2. `state/checkpoint.py` CheckpointStore 抽象加 6 方法
3. `state/backends/sqlalchemy_base.py` + `memory_backend.py` 实现（2 表）
4. 写 `orchestration/` 包：events → inbox → delivery → nodes → graph → scheduler → migration
5. 写 `tests/orchestration/` 全套
6. 全量测试 + ruff + mypy
7. 提交

---

## 11. 风险与回退

- **DAG 误配**：`validate()` 建图时返回未知节点/自环/回边（未配 max_iterations 保护）错误
- **Agent arun 缺失**：fallback `run_in_executor(run)`；不要求改 Agent 基类
- **消息增长**：TTL 7 天懒清理 + `delete_expired_messages` 定期调用
- **回环终止**：有界回环（max_iterations 计数）保证不无限循环；耗尽转告警而非静默
- **inbox 与 Agent 状态分离**：Agent 状态由 Agent 自身 checkpoint 负责；图只保证消息/回执持久