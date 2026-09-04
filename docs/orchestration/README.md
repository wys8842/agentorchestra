# orchestration — Agent 图/DAG 通信（P2 / M2）

把"子 Agent 是父 Agent 的 tool"升格为对等节点图：Agent 节点 + 消息 Inbox + 投递回执 + 条件边 + 有界回环。

设计见 [M2 spec](../superpowers/specs/2026-09-04-m2-agent-graph-design.md)。

## 模块组成

| 文件 | 职责 |
|------|------|
| `graph.py` | `Graph` / `Edge` / `Node` / `NodeContext` / `NodeOutput` / `GraphResult`（声明式） |
| `nodes.py` | `AgentNode`（arun，fallback run）/ `RouterNode` / `MergeNode` / `FunctionalNode` |
| `scheduler.py` | `GraphScheduler`：拓扑执行 + async 派发 + 条件路由 + 回环计数 |
| `inbox.py` | `Inbox`：持久化消息队列 + 回执 + TTL（7 天） |
| `delivery.py` | `DeliveryManager`：指数退避重试（≤5）+ `on_delivery_failed` |
| `events.py` | `NodeEvent` / `NodeEventType` / `DeliveryEvent`（trace/回调） |
| `migration.py` | `TaskToolGraphAdapter` + TaskTool→Graph 迁移指南 |

## 快速开始

```python
from agentorchestra.orchestration import Graph, AgentNode, RouterNode

g = Graph(store=checkpoint_store, max_iterations=3)   # 有界回环
g.add_node("coder", AgentNode(agent_factory=coder_factory))
g.add_node("reviewer", AgentNode(agent_factory=reviewer_factory))
g.add_node("verdict", RouterNode(
    lambda msg, ctx: "rejected" if "重做" in str(msg.get("task", "")) else "approved"))
g.add_node("tester", AgentNode(agent_factory=tester_factory))

g.add_edge("coder", "reviewer")
g.add_edge("reviewer", "verdict")
g.add_edge("verdict", "coder", when="rejected")   # 有界回环
g.add_edge("verdict", "tester", when="approved")

result = await g.run({"task": "初稿"}, thread_id="order-123", entry_node="coder")
# result.node_results / result.status ("completed" | "partially_failed") / result.errors
```

## 语义

| 概念 | 说明 |
|------|------|
| 条件边 | `when=None` 无条件激活；否则需 `NodeOutput.route` 匹配 |
| 有界回环 | 目标节点 iteration 达 `max_iterations` 后不再派发 + 记 error（不无限循环） |
| 多入口 | 无显式 entry_node 时启动所有无入边根节点（并行 fan-out） |
| 节点异常 | `output.error` → `partially_failed` + `on_node_error` 回调 |
| Inbox | 消息持久化（CheckpointStore.inbox_messages），7 天 TTL 可回溯 + ack 回执 |

## AgentNode 调用形态

async 核心：优先 `agent.arun(input)`；无 arun 的 Agent → `run_in_executor(run)`。
消息从 `message["task"]` 取（可用 `input_key` 定制）。

## TaskTool 兼容

`TaskTool` 保留不动（一次性简单子任务）。Graph 适用于协作/条件/回环场景。
迁移 helper：

```python
from agentorchestra.orchestration import TaskToolGraphAdapter
adapter = TaskToolGraphAdapter(agent_factory, agent_type="react")
g.add_node("coder", adapter.make_node())
```
