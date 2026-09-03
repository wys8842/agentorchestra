# Memory System Design — `agentorchestra/memory/`

- Status: Draft (awaiting user review)
- Date: 2026-09-03
- Approach: **方案 A** — 独立 `memory/` 包 + 轻量混合检索（关键词 + 复用 SymphonyLLM embedding）

## 1. 背景与目标

框架已有跨会话"半成品"：

- `context/history.py` `HistoryManager`：单会话短程，append-only + 摘要压缩。
- `core/session_store.py` `SessionStore`：把整个会话 JSON 文件化。
- `reflection_agent.py` 内置了进程内的简单 `Memory` 类，只供 Reflection 用。
- `context/builder.py` 注释：「MemoryTool 和 RAGTool 已被移除，如需使用请自行实现」。
- `context/__init__.py` 文档串提到过 `Compactor / NotesManager / ContextObserver`，但都**不存在**。
- `tools/base.py` 装饰器示例里出现过 `memory_add` 描述，是文档层面的"占位意图"。

**缺的是**：跨会话/跨任务，**对 Agent 自身可见的持久记忆**。这次设计只补这一块：
- 程序性记忆 → 已有 `skills/`，**不重做**。
- 工作/短期记忆 → 已有 `HistoryManager`，**不重做**。
- 补一个独立的"长期记忆 + 主动回忆"子系统（情景/事实/偏好/方法皆为同一类条目，按 `type` 区分）。

### 范围（v1）

| 包含 | 不包含（未来） |
|------|--------------|
| 跨会话持久记忆条目（fact / preference / episode / procedure） | 端到端向量数据库（chroma/milvus 等） |
| 关键词 + 余弦相似度混合检索 | 神经图谱/结构化记忆（需更复杂融合） |
| 复用 `SymphonyLLM` 提供 embedding（失败降级关键词） | 多用户/多 Agent 命名空间隔离（v1 单空间，metadata 区分来源） |
| `MemorySave` / `MemoryRecall` 内置工具 + 主动调用 | 记忆衰减/遗忘曲线（v1 仅 `importance`/`access_count` 字段占位） |
| run 开始自动注入相关记忆（**可关**） | 记忆编辑/合并 UI |

## 2. 架构

```
agentorchestra/
└── memory/
    ├── __init__.py       # 导出 MemoryManager / MemoryEntry / MemoryType / MemorySaveTool / MemoryRecallTool
    ├── models.py         # MemoryType (Enum) + MemoryEntry (dataclass)
    ├── storage.py        # MemoryStore + 三种后端（InMemory / Jsonl / SQLite）
    ├── index.py          # KeywordIndex（倒排）+ HybridRetriever（混合排序）
    ├── embedder.py       # Embedder：封装 SymphonyLLM embedding，缓存 + 失败降级
    ├── summarizer.py     # Summarizer：会话历史 → 候选记忆条目（轻量 LLM）
    ├── manager.py        # MemoryManager：Agent 挂载的统一入口（add/recall/update/delete/stats）
    └── tools.py          # MemorySaveTool / MemoryRecallTool（注册进 ToolRegistry）
```

每个模块一个职责，能独立测试：

- `MemoryEntry` 是纯数据模型，无外部依赖。
- `MemoryStore` 只关心字节级 CRUD，不懂"相似度/关键词"。
- `KeywordIndex` 与 `HybridRetriever` 只接受 embedding 与条目，处理召回与排序。
- `Embedder` 只把字符串转成向量，失败时返回 `None` 即可。
- `Summarizer` 把对话文本转成"记忆条目候选"，是 LLM 调用的唯一封装。
- `MemoryManager` 是上层接口，给 Agent/工具用，不暴露底层后端。
- `MemorySaveTool` / `MemoryRecallTool` 走标准 `Tool` 协议（与 `SkillTool` 同接口），便于注册到任意 `ToolRegistry`。

## 3. 数据模型（`memory/models.py`）

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class MemoryType(str, Enum):
    FACT       = "fact"        # 持久事实：用户/项目/环境
    PREFERENCE = "preference"  # 用户偏好与约定
    EPISODE    = "episode"     # 情景记忆：做过的任务/事件
    PROCEDURE  = "procedure"   # 方法/流程经验（轻量版，与 skills 互补）


@dataclass
class MemoryEntry:
    id: str
    type: MemoryType
    content: str
    tags: List[str] = field(default_factory=list)
    importance: float = 0.5                 # 0.0 ~ 1.0
    embedding: Optional[List[float]] = None  # 与 content 同步存
    source_session: str = ""                 # 元数据，不参与隔离
    source_agent: str = ""
    created_at: str = ""    # ISO8601 UTC
    updated_at: str = ""
    access_count: int = 0
    last_accessed_at: Optional[str] = None

    def touch(self) -> None: ...   # updated_at = now
    def accessed(self) -> None: ...  # access_count += 1, last_accessed_at = now
    def to_dict(self) -> dict: ...  # 序列化（embedding 单独存，JSON 友好）
    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry": ...
```

字段说明：
- `id` 使用 `uuid4().hex`（短 16 字节即可）。
- `embedding` 在 `to_dict` 时**排除**（单独表存 BLOB/REAL[]）；从 `from_dict` 单独由 `MemoryStore` 合并。
- `importance` 是写入时由调用方/工具声明，未来用作排序权重之一（v1 仅存值）。

## 4. 存储层（`memory/storage.py`）

借鉴 `ontology/storage/backends.py` 的抽象，三个后端 + 一个 `MemoryStore` 包装层：

```python
class BaseMemoryBackend(ABC):
    @abstractmethod
    def upsert(self, entry: MemoryEntry) -> None: ...
    @abstractmethod
    def get(self, entry_id: str) -> Optional[MemoryEntry]: ...
    @abstractmethod
    def delete(self, entry_id: str) -> bool: ...
    @abstractmethod
    def all(self) -> List[MemoryEntry]: ...          # 全量（用于关键词索引构建）
    @abstractmethod
    def save_embedding(self, entry_id: str, vec: List[float]) -> None: ...
    @abstractmethod
    def get_embedding(self, entry_id: str) -> Optional[List[float]]: ...
    @abstractmethod
    def stats(self) -> dict: ...
    def close(self) -> None: pass


class InMemoryBackend(BaseMemoryBackend): ...
class JsonlBackend(BaseMemoryBackend): ...     # memory/memories.jsonl，追加写
class SqliteBackend(BaseMemoryBackend): ...     # memory/memories.db（WAL）
```

**默认后端 = SQLite**（与 ontology 一致，跨进程、可并发、事务安全）。

`MemoryStore` 是上层统一接口（业务侧只用它）：

```python
class MemoryStore:
    def __init__(self, backend: BaseMemoryBackend): ...
    # 上层 CRUD
    def upsert(self, entry: MemoryEntry) -> None: ...
    def get(self, entry_id: str) -> Optional[MemoryEntry]: ...
    def delete(self, entry_id: str) -> bool: ...
    def iter_all(self) -> Iterable[MemoryEntry]: ...
    def stats(self) -> dict: ...
```

`MemoryStore` 内部不维护倒排索引；索引由 `KeywordIndex` 启动时从 `iter_all()` 构建并增量更新。

## 5. 嵌入与检索（`embedder.py` + `index.py`）

### 5.1 `Embedder`

```python
class Embedder:
    """复用 SymphonyLLM 获取 embedding；失败降级。"""

    def __init__(
        self,
        llm: Optional["SymphonyLLM"] = None,
        enabled: bool = True,
        cache: Optional[Dict[str, List[float]]] = None,
    ):
        self.llm = llm
        self.enabled = enabled
        self._cache = cache if cache is not None else {}

    def embed_texts(self, texts: List[str]) -> Optional[List[List[float]]]:
        """返回 None 表示不可用；否则返回与输入对齐的向量列表。
        失败时（超时/解析错/未启用）抛 EmbeddingUnavailable。"""
        ...

    def embed(self, text: str) -> Optional[List[float]]:
        ...

    @property
    def available(self) -> bool: ...
```

实现要点：
- 通过 `SymphonyLLM` 的 `base_url` 追加 `/embeddings` 路径，POST OpenAI 兼容请求体（绝大多数 Anthropic/Gemini 兼容层都支持）。
- 解析响应，标准化为 `List[float]`。
- 缓存：以 `sha256(text)` 为键，命中即返回（避免重复调用）。
- 不可用信号：通过抛 `EmbeddingUnavailable` 异常 + `available=False`；`HybridRetriever` 捕获后自动降级。

### 5.2 `KeywordIndex`

启动时一次性从 `MemoryStore.iter_all()` 构建倒排：

```python
class KeywordIndex:
    def __init__(self): ...
    def build(self, entries: Iterable[MemoryEntry]) -> None: ...
    def update(self, entry: MemoryEntry) -> None: ...
    def delete(self, entry_id: str) -> None: ...
    def search(self, query: str, top_n: int = 200) -> List[str]:
        """返回候选 memory_id 列表。"""
        ...
```

分词策略（不引入 jieba 等额外依赖）：使用 `re.findall(r"[A-Za-z0-9_]+|[一-龥]", text.lower())`，中英混合都能切。score = 词频累加（标题/标签加权）。

### 5.3 `HybridRetriever`

```python
class HybridRetriever:
    def __init__(
        self,
        store: MemoryStore,
        keyword_index: KeywordIndex,
        embedder: Embedder,
        embed_normalize: bool = True,
    ): ...

    def recall(
        self,
        query: str,
        top_k: int = 5,
        types: Optional[List[MemoryType]] = None,
    ) -> List[MemoryEntry]:
        """
        1. 关键词预筛 -> 候选 top_n
        2. embedder 不可用：返回关键词打分排序结果
        3. embedder 可用：对候选算相似度，融合关键词 + 余弦，归一化后取 top_k
        """
        ...
```

融合公式：

```
score = α * kw_score_normalized + (1 - α) * cos_sim_normalized   # 默认 α = 0.3
```

候选集 ≥ 阈值时再调一次 `Embedder.embed(query)`，避免重复。

## 6. 写入路径

### 6.1 工具主动（默认开启）

`MemorySaveTool` / `MemoryRecallTool` 与 `SkillTool` 同接口，挂在 `ToolRegistry`：

```python
class MemorySaveTool(Tool):
    name = "memory_save"
    description = "把一条信息记入长期记忆（fact/preference/episode/procedure）"
    expandable = False
    parameters = [
        ToolParameter("content", "string", "要记的内容", required=True),
        ToolParameter("type",    "string", "类型: fact/preference/episode/procedure",
                      required=False, default="fact"),
        ToolParameter("tags",    "string", "逗号分隔的标签", required=False, default=""),
        ToolParameter("importance", "number", "重要性 0~1", required=False, default="0.5"),
    ]
    def run(self, params) -> ToolResponse:
        ...

class MemoryRecallTool(Tool):
    name = "memory_recall"
    description = "从长期记忆中按 query 检索相关条目"
    ...
    parameters = [
        ToolParameter("query",  "string", "查询文本", required=True),
        ToolParameter("type",   "string", "限定类型（可空）", required=False, default=""),
        ToolParameter("top_k",  "number", "返回数量", required=False, default="5"),
    ]
    def run(self, params) -> ToolResponse:
        ...
```

注册方式（与 `SkillTool` 完全一致）：

```python
# Agent.__init__ 中按 Config 自动装配
if self.config.memory_enabled and self.tool_registry:
    from .memory import MemoryManager
    from .memory.tools import MemorySaveTool, MemoryRecallTool

    self.memory_manager = MemoryManager.from_config(self.config, llm=self.llm)
    self.tool_registry.register_tool(MemorySaveTool(self.memory_manager))
    self.tool_registry.register_tool(MemoryRecallTool(self.memory_manager))
```

### 6.2 run 结束自动总结（**默认关闭**）

启用时（`memory_auto_summarize=True`）触发点：

- 同步 `run()`：在子类 `run()` 调用栈末尾难以无侵入挂钩，**改用**用户调用层 `agent.run(...)` 时由基类通过包装实现自动总结（v1 仅在 `arun()` 路径实现，文档说明）。
- 异步 `arun(...)`：在 `AGENT_FINISH` 事件之后调用 `_auto_memorize(...)`（不影响 `result`）。

```python
async def _auto_memorize(self, input_text: str, result: str):
    history = self.history_manager.get_history()
    candidates = self.memory_summarizer.extract(input_text, history, result)
    for c in candidates:
        self.memory_manager.remember(...)
```

`Summarizer.extract(...)` 调一次轻量 LLM，要求返回严格 JSON：

```json
[
  {"type": "fact", "content": "...", "tags": "..., ...", "importance": 0.7},
  {"type": "preference", "content": "...", "tags": "...", "importance": 0.6}
]
```

调用失败/超时 → 记录 `logger.warning`，**不抛**，不影响 run 主流程。

## 7. 回忆注入（每次 run 自动，默认开启 + 可关）

每次 `run()` / `arun()` 开始时，若 `memory_auto_recall=True` 且 query 非空：

1. `entries = self.memory_manager.recall(input_text, top_k=self.config.memory_recall_top_k)`
2. 把条目格式化为固定前缀，注入到 `system_prompt` 之后：

```
[你的系统提示...]
---
以下是与该任务相关的过往记忆（来自历史会话）：
- [fact] 用户偏好简洁中文回复
- [episode] 上次已为该项目搭建 ontology 骨架
若与当前任务无关可忽略。
```

**实现位置**：复用 `ContextBuilder.build(...)` 时扩展一条 `[Memory]` section（`metadata["type"] = "memory"`），由现有 `_structure` 自动按位置插入；或更简单——在 `_build_messages_for_llm` 这类统一消息构造处把前缀字符串拼到第一条 `system` 消息内容之后。

精确注入点 v1 选择后者（影响面小），并在代码处注释：

```python
# agent.py (arun 入口附近)
if self.memory_manager and self.config.memory_auto_recall and input_text:
    recalled = self.memory_manager.recall(input_text,
        top_k=self.config.memory_recall_top_k)
    if recalled:
        prefix = self._format_memory_prefix(recalled)
        self._system_prompt = (prefix + "\n\n" + (self.system_prompt or "")).strip()
```

**绝不修改** `HistoryManager` 内容；仅追加到 `system_prompt`。

## 8. Agent 集成点

`core/agent.py` 在 `__init__` 中：

```python
# 已有：HistoryManager / Truncator / TokenCounter / TraceLogger / Skills / MCP / Ontology / Session / Subagent / TodoWrite / DevLog
# 新增：memory_manager（仅在 memory_enabled 时）
from agentorchestra.memory import MemoryManager
self.memory_manager: Optional[MemoryManager] = None
if self.config.memory_enabled:
    self.memory_manager = MemoryManager.from_config(self.config, llm=self.llm)
    if self.tool_registry and self.config.memory_auto_register_tools:
        from agentorchestra.memory.tools import MemorySaveTool, MemoryRecallTool
        self.tool_registry.register_tool(MemorySaveTool(self.memory_manager))
        self.tool_registry.register_tool(MemoryRecallTool(self.memory_manager))
```

`memory_manager` 的生命周期与 Agent 同进程；`Agent.run()` / `Agent.arun()` 在开始/结束按 §6/§7 调用。

## 9. 配置（`core/config.py` 新增字段）

```python
# 记忆系统
memory_enabled: bool = False                # 主开关
memory_backend: str = "sqlite"              # sqlite / jsonl / memory
memory_db_path: str = "memory/memories.db"  # SQLite 文件
memory_jsonl_path: str = "memory/memories.jsonl"

memory_auto_register_tools: bool = True     # 启动时自动注册 MemorySave/Recall 工具
memory_auto_recall: bool = True             # run 开始自动注入相关记忆
memory_auto_summarize: bool = False         # run 结束自动提炼（默认关闭，隐式 LLM 成本）

memory_recall_top_k: int = 5
memory_embedding_enabled: bool = True       # 关闭则纯关键词
memory_dedup_threshold: float = 0.92        # 写入去重相似度阈值
memory_max_entries: int = 10000             # 容量上限（v1 仅记录统计）
```

## 10. 错误处理与降级

| 失败场景 | 行为 |
|----------|------|
| `Embedder.embed_texts` 抛错 | `MemoryManager.recall` 捕获 → 切到关键词检索 → `logger.warning`，返回关键词排序结果 |
| `SymphonyLLM` 不可用 | `Embedder.available=False`，整个系统退化为关键词检索；Agent 不报错 |
| `MemoryStore.upsert` 失败（如磁盘满） | 工具返回 `ToolResponse.error`；自动总结路径 `logger.warning` 后跳过本条 |
| 自动总结 LLM 调用失败/超时 | `logger.warning`，跳过本轮；不影响 `run()` 返回值 |
| `memory_enabled=False` | `memory_manager is None`；§6/§7 全跳过；Agent 行为零变化 |
| 记忆目录不可写 | `MemoryManager.from_config` 创建时一次性探测失败 → 关闭 `memory_manager`（仅告警） |

设计原则：**任何记忆相关失败都不得让 Agent 主流程崩溃**。

## 11. 测试（`tests/`）

- `tests/test_memory_models.py`：`MemoryEntry` 序列化/反序列化、字段校验、`access/touch`。
- `tests/test_memory_storage.py`：三后端各覆盖 `upsert/get/delete/all/save_embedding/stats`。
- `tests/test_memory_retrieval.py`：
  - 关键词预筛正确性
  - 有 embedding 时融合排序
  - embedding 不可用降级到关键词
  - 写入去重（同内容再次写入应更新 `updated_at`，不增 id）
- `tests/test_memory_tools.py`：
  - `MemorySaveTool.run` 入参边界（空 content/非法 type）
  - `MemoryRecallTool.run` type 过滤 + top_k
- `tests/test_memory_agent.py`（mock `SymphonyLLM`）：
  - `memory_auto_recall=True` 时 run 开始注入前缀
  - `memory_auto_recall=False` 时不注入
  - `memory_auto_summarize=True` 时 run 结束有 `remember_batch` 调用
  - 工具注册到 `tool_registry` 且可被 Agent 调用
- mypy：`memory/` 新代码 0 error（复用仓库 mypy 配置）。
- ruff：lint 通过。

## 12. 未来演进（非 v1 范围）

- 命名空间 / 多用户隔离（`MemoryStore.upsert(scope=..., owner=...)`）。
- 记忆衰减：按 `importance` × `last_accessed_at` 在 `recall` 阶段给相似度打分乘衰减系数。
- 记忆编辑与合并：发现近似条目时主动询问 Agent 是否合并。
- 本地专用 embedding 后端（`agentorchestra[embeddings]` 可选依赖）。
- 与 `ontology` 融合：把"长期记忆"作为 Ontology 里的 `memory_entry` 对象，复用治理（审计/分支）。本设计与之**不冲突**，仅存储位置不同；后续可加配置项切换。
- v2 引入 `Compactor`/`NotesManager`/`ContextObserver`（呼应 `context/__init__.py` 文档串），与本记忆系统**正交**（这些是上下文层的总结/结构化笔记，不涉及跨会话持久）。

## 13. 接入清单（实施时落地）

1. 新建 `agentorchestra/memory/` 八个文件，按本设计实现。
2. `core/config.py` 新增 9 个配置字段（含默认值）。
3. `core/agent.py` 在 `__init__` 末尾增加 `memory_manager` 装配；在 `arun` 入口附近增加前缀注入；在 `arun` 完成后增加可选自动总结调用。
4. `agentorchestra/version.py` 不变更。
5. `docs/memory/README.md` 新增，说明 API 与示例。
6. `CHANGELOG.md` 新增条目（v1.x — Memory subsystem）。
