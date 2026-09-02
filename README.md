# Symphony

**Symphony** 是一个企业级多智能体与 Ontology 编排框架。

它把"智能决策"（Agent）与"业务语义"（企业级 Ontology，
如同管弦乐团各声部和谐演奏：Agent 负责思考与决策，Ontology 负责业务对象与操作，
Workflow/Scheduler/Transaction 负责执行编排。

## 特性

- **多智能体**：Simple / ReAct / Reflection / PlanSolve 四种范式 + 子代理机制
- **企业级 Ontology**：对象类型 / 动作 / 函数 / 接口，统一业务语义建模
- **执行编排**：Workflow（流程）、Scheduler（调度）、Transaction（事务补偿）
- **治理**：权限 / 审计 / 分支 / 物化
- **工具生态**：内置工具（文件/计算/子代理/技能/MCP）+ 自定义 Tool
- **上下文工程**：历史管理、Token 预算、压缩、GSSC 流水线
- **可观测**：TraceLogger 双格式（JSONL+HTML）审计、事件系统、流式输出
- **企业级运维**：结构化日志、Prometheus 指标、分布式追踪、限流、配置热更新、健康检查、监控端点

## 安装

```bash
pip install agentorchestra            # 核心
pip install "agentorchestra[all]"     # 全部可选依赖（MCP/Neo4j/Gemini 等）
```

## 快速开始

```python
from agentorchestra.core.config import Config
from agentorchestra.core.llm import SymphonyLLM
from agentorchestra.agents.react_agent import ReActAgent
from agentorchestra.tools.registry import ToolRegistry

llm = SymphonyLLM(provider="openai", model="gpt-4o", api_key="sk-xxx")
registry = ToolRegistry()

agent = ReActAgent(name="Assistant", llm=llm, tool_registry=registry)
result = agent.run("帮我分析这个项目")
```

## 架构

```
应用层
  └─ Agent 层（agents + core）        决策 / 工具调用 / 上下文 / 事件
       └─ Tool 契约（tools + context）  schema / 执行 / 注入
            └─ 业务语义层（ontology）   对象/动作/函数/接口 + 治理 + 编排
                 └─ 数据层             数据库 / 文件 / 外部系统 / MCP
```

## 文档

| 模块 | 文档 |
|------|------|
| core | [docs/core/README.md](docs/core/README.md) |
| agents | [docs/agents/README.md](docs/agents/README.md) |
| tools | [docs/tools/README.md](docs/tools/README.md) |
| context | [docs/context/README.md](docs/context/README.md) |
| observability | [docs/observability/README.md](docs/observability/README.md) |
| ontology | [docs/ontology/README.md](docs/ontology/README.md) |

## 开发

```bash
pip install "agentorchestra[dev]"
pytest              # 运行测试
ruff check .        # 代码检查
```

## License

MIT
