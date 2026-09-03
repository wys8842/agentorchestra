# memory - 跨会话持久记忆

v1 长期记忆子系统，让 Agent 在多次会话间记住用户偏好、项目事实、过往事件与方法经验。

- 设计：`docs/superpowers/specs/2026-09-03-memory-system-design.md`
- 计划：`docs/superpowers/specs/2026-09-03-memory-system-plan.md`

## 模块组成

| 文件 | 职责 |
|------|------|
| `__init__.py` | 公共导出 `MemoryManager / MemoryEntry / MemoryType` |
| `models.py` | `MemoryType` 枚举 + `MemoryEntry` 数据模型 |
| `storage.py` | 三种后端（`InMemoryBackend` / `JsonlBackend` / `SqliteBackend`）+ `MemoryStore` 包装 |
| `embedder.py` | 复用 `SymphonyLLM` 的 embedding 封装（缓存 + 协议失败降级） |
| `index.py` | `KeywordIndex`（倒排） + `HybridRetriever`（关键词 + 余弦融合） |
| `manager.py` | `MemoryManager` 统一入口（Agent 挂载点） |
| `tools.py` | `MemorySaveTool` / `MemoryRecallTool`（注册进 `ToolRegistry`） |
| `summarizer.py` | 会话历史 → 候选记忆条目（轻量 LLM） |

## 记忆类型

| 类型 | 用途 |
|------|------|
| `fact` | 持久事实：用户/项目/环境信息 |
| `preference` | 用户偏好与约定 |
| `episode` | 情景记忆：做过的任务/事件 |
| `procedure` | 方法/流程经验（与 `skills` 互补，轻量版） |

## 配置（`core/config.py`）

```python
memory_enabled: bool = False               # 主开关
memory_backend: str = "sqlite"             # sqlite / jsonl / memory
memory_db_path: str = "memory/memories.db"
memory_jsonl_path: str = "memory/memories.jsonl"

memory_auto_register_tools: bool = True    # 自动注册 MemorySave / Recall 工具
memory_auto_recall: bool = True            # run 开始自动注入相关记忆
memory_auto_summarize: bool = False        # run 结束自动提炼（默认关闭）

memory_recall_top_k: int = 5
memory_embedding_enabled: bool = True      # 关闭则纯关键词
memory_dedup_threshold: float = 0.92
memory_max_entries: int = 10000
```

## 快速开始

```python
from agentorchestra.core.config import Config
from agentorchestra.core.llm import SymphonyLLM
from agentorchestra.agents.react_agent import ReActAgent
from agentorchestra.tools.registry import ToolRegistry

cfg = Config(
    memory_enabled=True,
    memory_backend="sqlite",
    memory_auto_recall=True,       # 默认开
    memory_auto_summarize=False,    # 默认关闭
)
llm = SymphonyLLM(model="gpt-4o", api_key="sk-xxx",
                   base_url="https://api.openai.com/v1")
registry = ToolRegistry()
agent = ReActAgent(name="Assistant", llm=llm,
                    config=cfg, tool_registry=registry)

# 启动后 MemorySave / MemoryRecall 工具已自动注册到 registry
# run 开始会自动注入 top-K 相关记忆到 system_prompt 之后
result = agent.run("帮我回顾上次项目的进展")
```

## 主动调用工具

`MemorySaveTool` 与 `MemoryRecallTool` 与 `SkillTool` 同接口，注册到 `ToolRegistry` 后 Agent 自动可用：

```python
# 通过 Agent 调工具（Agent 会自动选用）：
agent.run("记住：该项目使用 agentorchestra 框架，标签 Symphony/Python")
agent.run("我之前偏好过什么语言？")
```

工具入参：

- `MemorySaveTool(content, type=fact|preference|episode|procedure, tags="a,b", importance=0.5)`
- `MemoryRecallTool(query, type?, top_k=5)`

## 检索机制

混合检索（关键词 + 向量）：

1. **关键词预筛**：`_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-龥]")` 中英混合分词，倒排索引打分（标签命中加权 ×3）
2. **向量精排**：复用 `SymphonyLLM` 的 `/embeddings` 协议，余弦相似度排序
3. **融合**：α × kw_norm + (1−α) × cos_norm，α 默认 0.3

**降级链**：`SymphonyLLM` embedding 不可用 → 自动切关键词检索，不报错。

## 跨会话工作流

1. 用户在某次会话中说："我偏好简洁中文回复"
2. Agent 调 `MemorySaveTool` → 落库 SQLite `memory/memories.db`
3. 下一次新会话 → `run()` 开始 → `_memory_inject_prefix` 自动从 `recall` 取 top-K → 拼到 `system_prompt` 之后
4. Agent 看到这条偏好，无需用户重新交代

## 写入去重

`MemoryManager.remember()` 在写入前会：

1. 用 embedder 算新条目的向量
2. 遍历同 type 已有条目计算余弦相似度
3. 若 ≥ `memory_dedup_threshold`（默认 0.92）→ **更新**该条目（`updated_at` 推进、`tags` 取并集、`importance` 取 max），不新增
4. embedder 不可用 → 跳过去重，直接 upsert

## 自动总结（可选）

启用 `memory_auto_summarize=True` 后，每次 `arun()` 结束会自动：

1. 取本轮 user 输入 + 历史消息 + 最终回答
2. 调 `Summarizer.extract(...)`（轻量 LLM，温度 0.2）→ 严格 JSON 数组候选
3. `MemoryManager.remember_batch(...)` 去重入库
4. 失败/超时 → 跳过本轮，不影响主流程

**默认关闭**，因隐式 LLM 成本。

## 存储后端

| 后端 | 用途 | 文件 |
|------|------|------|
| `sqlite` | **默认**，跨进程、安全 | `memory/memories.db`（WAL） |
| `jsonl` | 人类可读、git 友好 | `memory/memories.jsonl` + `*.emb.jsonl` |
| `memory` | 测试/单进程演示 | 不写盘 |

切换：`Config(memory_backend="jsonl")` 或 `"memory"`。

## 降级原则

**任何记忆层失败不得让 Agent 主流程崩溃**：

| 场景 | 行为 |
|------|------|
| Embedding 不可用 | 切关键词检索，warn 一次 |
| SQLite 写失败 | 工具返回 `ToolResponse.error`，自动总结 warn 后跳过 |
| 总结 LLM 失败 | warn，跳过本轮 |
| 目录不可写 | `MemoryManager.from_config` 失败 → `memory_manager = None`，Agent 照常运行 |

## 测试

现有 182 用例全部通过。Memory 单元测试可在后续 PR 补：

- `tests/test_memory_models.py`
- `tests/test_memory_storage.py`（三后端参数化）
- `tests/test_memory_retrieval.py`（含降级）
- `tests/test_memory_manager.py`
- `tests/test_memory_tools.py`
- `tests/test_memory_agent.py`（mock LLM）

## 边界

- 不重建程序记忆（用 `skills/`）
- 不重建工作/短期记忆（用 `HistoryManager`）
- v1 单记忆空间（`source_session` 仅元数据，不参与隔离）；多用户/多 Agent 命名空间隔离留待后续

## API 速览

```python
from agentorchestra.memory import MemoryManager, MemoryEntry, MemoryType

mgr = MemoryManager.from_config(cfg, llm=llm)

# 写入
eid = mgr.remember(content="...", type=MemoryType.FACT, tags=["..."])
mgr.remember_batch([{"content": "...", "type": "fact", "importance": 0.6}, ...])

# 检索
hits: list[MemoryEntry] = mgr.recall(query, top_k=5, types=[MemoryType.FACT])

# 列出
items = mgr.list(types=[MemoryType.PREFERENCE], limit=20)

# 删除
mgr.forget(entry_id)

# 统计
mgr.stats()
```