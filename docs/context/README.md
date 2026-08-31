# context - 上下文工程

管理 Agent 的上下文：历史存储、Token 计量、压缩、上下文构建（GSSC 流水线）。

## 模块组成

| 文件 | 职责 |
|------|------|
| `history.py` | `HistoryManager`：历史消息管理（追加/压缩/序列化） |
| `token_counter.py` | `TokenCounter`：Token 计数（缓存 + 增量） |
| `builder.py` | `ContextBuilder`：GSSC 流水线（Gather-Select-Structure-Compress） |
| `truncator.py` | `ObservationTruncator`：工具输出截断 |

## 1. HistoryManager — 历史管理

```python
from symphony.context.history import HistoryManager

manager = HistoryManager(min_retain_rounds=10)
manager.append(Message("你好", "user"))
manager.append(Message("hi", "assistant"))

history = manager.get_history()      # List[Message]
manager.compress("前几轮的摘要")       # 压缩旧轮次，保留最近 N 轮
```

**只追加**：append-only，缓存友好（Token 计数可增量）。

## 2. TokenCounter — Token 计量

```python
from symphony.context.token_counter import TokenCounter

counter = TokenCounter(model="gpt-4")
tokens = counter.count_message(msg)      # 单条 + 缓存
total = counter.count_messages(history)  # 批量
```

**降级链**：tiktoken 编码 → cl100k_base → `len//4` 字符估算。

## 3. 压缩机制

Agent 的 `add_message()` 触发压缩检查：

```
_history_token_count > context_window * compression_threshold (128000*0.8)
    ↓
_compress_history():
  简单摘要（统计）或智能摘要（轻量 LLM 提炼）
    ↓
HistoryManager.compress() → [summary消息] + 最近 min_retain_rounds 轮
```

## 4. ContextBuilder — GSSC 流水线

```python
from symphony.context.builder import ContextBuilder, ContextConfig

builder = ContextBuilder(
    config=ContextConfig(max_tokens=8000),
    knowledge_provider=my_knowledge_provider,   # 可选：注入图谱知识
)
context = builder.build(
    user_query="问题",
    conversation_history=history,
    system_instructions="系统指令",
)
```

**GSSC 四阶段**：
- **Gather**：收集候选（系统指令 + 最近历史 + 知识包）
- **Select**：相关性 + 新近性打分，预算填充
- **Structure**：组织成 `[Role]/[Task]/[State]/[Evidence]/[Context]/[Output]`
- **Compress**：超预算按行截断

## 5. ObservationTruncator — 工具输出截断

```python
from symphony.context.truncator import ObservationTruncator

truncator = ObservationTruncator(max_lines=2000, truncate_direction="head")
result = truncator.truncate(tool_name="Read", output=long_text)
# → {truncated, preview, full_output_path, stats}
```

超长工具输出截断进上下文，完整结果保存到 `tool-output/` 文件。

## 在 Agent 中的集成

`Agent.__init__` 自动创建三个组件，`add_message()` 串联：

```python
self.history_manager = HistoryManager(...)
self.token_counter = TokenCounter(model=llm.model)
self.truncator = ObservationTruncator(...)
```
