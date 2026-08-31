# observability - 可观测性

Agent 执行的可观测能力：持久化轨迹记录 + 实时事件系统。

## 模块组成

| 文件 | 职责 |
|------|------|
| `trace_logger.py` | `TraceLogger`：双格式（JSONL+HTML）执行轨迹记录 |

（生命周期事件 `core/lifecycle.py` 和流式 `core/streaming.py` 是配套机制，见 [core](../core/README.md)）

## TraceLogger — 双格式轨迹记录

记录 Agent 执行的完整轨迹，供事后审计与分析。

```python
from agentorchestra.observability import TraceLogger

logger = TraceLogger(
    output_dir="memory/traces",
    sanitize=True,                    # 脱敏 API Key/路径
)
logger.log_event("session_start", {"agent_name": "MyAgent"})
logger.log_event("tool_call", {"tool_name": "Read"}, step=1)
logger.finalize()                     # 生成统计 + 关闭文件
```

**双格式输出**：
- `trace-{session_id}.jsonl` — 机器可读，流式追加，可用 jq 分析
- `trace-{session_id}.html` — 人类可读，暗色主题，统计面板

**记录的事件**：

| 事件 | 含义 |
|------|------|
| `session_start` / `session_end` | 会话开始/结束 |
| `message_written` | 用户消息 |
| `model_output` | LLM 输出（含 usage/tokens/cost） |
| `tool_call` / `tool_result` | 工具调用轨迹 |
| `error` | 错误 |
| `hook_timeout` / `hook_error` | 生命周期钩子异常 |

**统计面板**（finalize 时生成）：总步数 / 总 Token / 总成本 / 时长 / 工具调用表 / 错误列表。

## 三套可观测机制

| 机制 | 受众 | 方向 | 用途 |
|------|------|------|------|
| `TraceLogger.log_event()` | 开发者/审计 | 写文件 | 事后分析、成本、排障 |
| `_emit_event()`（钩子） | 开发者 | 实时回调 | on_start/on_finish 等通知 |
| `StreamEvent`（流式） | 最终用户 | SSE/JSON | 前端打字机效果、进度 |

## 使用示例

```python
from agentorchestra.observability import TraceLogger

with TraceLogger(output_dir="memory/traces") as logger:
    logger.log_event("session_start", {"agent_name": "Assistant"})
    # ... 执行逻辑 ...
    # 异常时 __exit__ 自动记录 error + finalize
```

## 事件系统

- **AgentEvent**（core/lifecycle.py）：生命周期钩子回调（5 秒超时 + 异常隔离）
- **StreamEvent**（core/streaming.py）：流式输出（LLM_CHUNK/TOOL_CALL/AGENT_FINISH）
