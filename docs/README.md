# Symphony 框架文档

**Symphony** 是一个灵活、可扩展的多智能体框架，集成企业级 Ontology 与 Skills 知识外化，
把"智能决策"（Agent）与"业务语义"（Ontology）统一编排，如同管弦乐团各声部和谐演奏。

## 模块索引

| 模块 | 说明 | 文档 |
|------|------|------|
| [core](core/README.md) | 核心层：LLM、Config、Message、Agent 基类、会话、可靠性、运维 | 核心运行时 |
| [agents](agents/README.md) | Agent 范式：Simple / ReAct / Reflection / PlanSolve / Loop | 五种智能体 |
| [tools](tools/README.md) | 工具系统：Tool 基类、注册表、内置工具 | 工具能力 |
| [context](context/README.md) | 上下文工程：历史、压缩、Token 计数、GSSC | 上下文管理 |
| [observability](observability/README.md) | 可观测性：Trace 记录、事件系统 | 审计与观测 |
| [ontology](ontology/README.md) | 企业级 Ontology：对象/动作/函数/接口/治理/流程 | 业务语义层 |
| [memory](memory/README.md) | 跨会话持久记忆：长期/短期之外的"跨任务记忆" | 持久化与回忆 |

## 架构总览

```
┌─────────────────────────────────────────────────────────┐
│  应用层：业务用户 / 场景                                   │
├─────────────────────────────────────────────────────────┤
│  Agent 层（agents + core）                               │
│    决策 / 工具调用 / 上下文 / 事件 / 审计                    │
├─────────────────────────────────────────────────────────┤
│  Tool 契约（tools + context + observability）            │
│    schema / 执行 / 注入 / 上下文 / 轨迹                    │
├─────────────────────────────────────────────────────────┤
│  业务语义层（ontology）                                   │
│    对象/动作/函数/接口 + 治理 + 流程编排/调度/事务            │
├─────────────────────────────────────────────────────────┤
│  数据层：数据库 / 文件 / 外部系统 / MCP                     │
└─────────────────────────────────────────────────────────┘
```

## 核心价值

- **多智能体**：五种 Agent 范式（Simple/ReAct/Reflection/PlanSolve/Loop）+ 子代理机制
- **企业级 Ontology**：对象类型/链接/动作/函数/接口统一建模，权限/审计/分支/物化治理
- **执行编排**：Workflow（流程）、Scheduler（调度）、Transaction（事务补偿）
- **工具生态**：内置工具（文件/计算/子代理/技能/MCP）+ 自定义 Tool
- **Skills 知识外化**：渐进式披露（元数据 + 按需 body），大幅节省 Token
- **跨会话持久记忆**：混合检索（关键词+向量）+ 自动注入/主动工具调用
- **可观测**：TraceLogger 双格式（JSONL+HTML）审计，事件系统实时回调
- **上下文工程**：历史管理、Token 预算、压缩、GSSC 流水线

## 快速开始

```python
from agentorchestra.agents.react_agent import ReActAgent
from agentorchestra.core.llm import SymphonyLLM
from agentorchestra.tools.registry import ToolRegistry

# 自动按 base_url 识别提供商；也可用 LLM_MODEL_ID/LLM_API_KEY/LLM_BASE_URL 环境变量
llm = SymphonyLLM(
    model="gpt-4o",
    api_key="sk-xxx",
    base_url="https://api.openai.com/v1",
)
registry = ToolRegistry()

agent = ReActAgent(
    name="Assistant",
    llm=llm,
    tool_registry=registry,
)
result = agent.run("帮我分析这个项目")
```

## 版本

见 [version.py](../../agentorchestra/version.py)。
