# agents - Agent 范式

四种 Agent 实现，继承 `core/agent.py` 的 `Agent` 基类，通过 `agents/factory.py` 工厂创建。

## Agent 类型

| Agent | 范式 | 特点 |
|-------|------|------|
| `SimpleAgent` | 简单对话 | 直接调用 LLM，可选工具调用 |
| `ReActAgent` | 推理-行动 | Thought/Finish 伪工具 + Function Calling，工具循环 |
| `ReflectionAgent` | 反思迭代 | 生成→反思→优化循环（Self-Refine） |
| `PlanSolveAgent` | 规划-执行 | Planner 生成计划 → Executor 逐步执行 |

## 创建与使用

### 1. SimpleAgent

```python
from symphony.agents.simple_agent import SimpleAgent

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
from symphony.agents.react_agent import ReActAgent

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
from symphony.agents.reflection_agent import ReflectionAgent

agent = ReflectionAgent(
    name="reflector",
    llm=llm,
    max_iterations=3,   # 反思迭代次数
)
result = agent.run("写一个高质量方案")
```

**流程**：执行任务 → 反思结果 → 优化改进 → 循环。

### 4. PlanSolveAgent

```python
from symphony.agents.plan_solve_agent import PlanSolveAgent

agent = PlanSolveAgent(name="planner", llm=llm)
result = agent.run("实现一个推荐系统")
```

**流程**：Planner 生成步骤计划 → Executor 按计划逐步执行。

## 工厂创建

```python
from symphony.agents.factory import create_agent, default_subagent_factory

agent = create_agent(
    agent_type="react",      # react/reflection/plan/simple
    name="sub",
    llm=llm,
    tool_registry=registry,
)
```

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
