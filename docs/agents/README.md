# agents - Agent 范式

五种 Agent 实现，继承 `core/agent.py` 的 `Agent` 基类，通过 `agents/factory.py` 工厂创建。

## Agent 类型

| Agent | 范式 | 特点 |
|-------|------|------|
| `SimpleAgent` | 简单对话 | 直接调用 LLM，可选工具调用 |
| `ReActAgent` | 推理-行动 | Thought/Finish 伪工具 + Function Calling，工具循环 |
| `ReflectionAgent` | 反思迭代 | 生成→反思→优化循环（Self-Refine） |
| `PlanSolveAgent` | 规划-执行 | Planner 生成计划 → Executor 逐步执行 |
| `LoopAgent` | 循环执行 | 通用 Function Calling 循环（无预设推理模板） |

> 所有 Agent 都提供同步 `run()` 与异步 `arun()`；`LoopAgent` 亦可作为通用多轮工具交互替代方案。

## 创建与使用

### 1. SimpleAgent

```python
from agentorchestra.agents.simple_agent import SimpleAgent

agent = SimpleAgent(
    name="assistant",
    llm=llm,
    system_prompt="你是助手",
    tool_registry=registry,        # 可选，提供则启用工具调用
)
result = agent.run("你好")
```

### 2. ReActAgent（最完整的工具型 Agent）

```python
from agentorchestra.agents.react_agent import ReActAgent

agent = ReActAgent(
    name="react",
    llm=llm,
    tool_registry=registry,
    max_steps=10,
)
result = agent.run("帮我分析项目架构")
```

**执行流程**：LLM Function Calling → 工具调用循环 → Finish 收尾：

```
Thought(记录推理) → Action(调用工具) → 观察结果 → ... → Finish(最终答案)
```

**内置伪工具**：
- `Thought`：显式记录推理（`_handle_builtin_tool` 处理）
- `Finish`：返回最终答案并终止

### 3. ReflectionAgent

```python
from agentorchestra.agents.reflection_agent import ReflectionAgent

agent = ReflectionAgent(
    name="reflector",
    llm=llm,
    max_steps=3,        # 最大反思迭代次数
    tool_registry=registry,   # 可选：反思过程中也支持工具调用
)
result = agent.run("写一个高质量方案")
```

**流程**：执行任务 → 反思结果 → 优化改进 → 循环。

### 4. PlanSolveAgent

```python
from agentorchestra.agents.plan_solve_agent import PlanSolveAgent

agent = PlanSolveAgent(name="planner", llm=llm, tool_registry=registry)
result = agent.run("实现一个推荐系统")
```

**流程**：Planner 生成步骤计划 → Executor 按计划逐步执行。

### 5. LoopAgent

```python
from agentorchestra.agents.loop_agent import LoopAgent

agent = LoopAgent(
    name="loop",
    llm=llm,
    tool_registry=registry,
    max_steps=5,        # 最大循环迭代次数
)
result = agent.run("帮我多轮查询并汇总结果")
```

**流程**：LLM Function Calling → 执行工具 → 结果反馈 → 继续循环，直到无工具调用或达到 `max_steps`。

## 工厂创建

```python
from agentorchestra.agents.factory import create_agent, default_subagent_factory

agent = create_agent(
    agent_type="react",   # react/reflection/plan/simple/loop
    name="sub",
    llm=llm,
    tool_registry=registry,
)
```

> `agents/__init__.py` 另导出 `PlanAndSolveAgent`（`PlanSolveAgent` 向后兼容别名）。

## 子代理机制

`Agent.run_as_subagent()` 提供上下文隔离：

```python
result = subagent.run_as_subagent(
    task="探索代码库",
    tool_filter=ReadOnlyFilter(),   # 限制工具
    return_summary=True,            # 返回摘要
)
```

子代理是**全新实例**（独立 HistoryManager/TokenCounter），执行后主代理状态自动恢复，只返回摘要。

## 异步与流式

所有 Agent 支持：
- `arun()` — 异步执行（带生命周期钩子）
- `arun_stream()` — 流式执行（StreamEvent 逐块输出）
