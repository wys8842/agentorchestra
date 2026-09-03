# Memory System Implementation Plan

- 对应设计：`docs/superpowers/specs/2026-09-03-memory-system-design.md`
- 仓库：`agentorchestra`
- 工作目录：`D:\proj\agentorchestra`

实施按依赖顺序拆为 7 个里程碑，每个里程碑都自带验证步骤。

---

## M0. 脚手架与 Config

**任务**
1. 新建 `agentorchestra/memory/` 目录与空文件骨架：
   - `__init__.py`、`models.py`、`storage.py`、`embedder.py`、`index.py`、`manager.py`、`tools.py`、`summarizer.py`
2. `core/config.py` 新增 9 个配置字段（见设计 §9），默认值严格按设计。
3. `core/__init__.py` 不需要改动（记忆系统独立模块）。
4. `agentorchestra/memory/__init__.py` 暂只导出占位：`from .models import MemoryType, MemoryEntry`（其余等实现后导出）。

**验证**
```bash
mypy agentorchestra/memory/        # 0 error（即使空也要过）
ruff check agentorchestra/memory/   # 0 error
python -c "from agentorchestra.core.config import Config; c=Config(); print(c.memory_enabled, c.memory_backend)"
```

---

## M1. 数据模型（`memory/models.py`）

**任务**
- 实现 `MemoryType(str, Enum)`：FACT/PREFERENCE/EPISODE/PROCEDURE（字符串值见设计 §3）
- 实现 `MemoryEntry` dataclass：
  - 字段：`id, type, content, tags, importance, embedding, source_session, source_agent, created_at, updated_at, access_count, last_accessed_at`
  - 方法：`touch()`、`accessed()`、`to_dict()`（排除 embedding）、`from_dict(d, embedding=None)`
- 工具函数：`now_iso()` → ISO8601 UTC 字符串

**验证**
- 单元测试 `tests/test_memory_models.py`：
  - `MemoryEntry` 序列化/反序列化（embedding 字段不出现于 dict）
  - `from_dict` 单独接受 embedding 参数
  - `touch()` / `accessed()` 修改时间戳与计数

---

## M2. 存储层（`memory/storage.py`）

**任务**
- `BaseMemoryBackend` 抽象接口（按设计 §4：upsert/get/delete/all/save_embedding/get_embedding/stats/close）
- `InMemoryBackend`：`Dict[str, MemoryEntry]` + `Dict[str, List[float]]`
- `JsonlBackend`：追加写 `memory/memories.jsonl`；读取时全量重放；embedding 存独立 `memory/memories.embeddings.jsonl`（可选）
- `SqliteBackend`：
  - 表 `memories(id PK, type, content TEXT, tags TEXT(CSV), importance REAL, source_session, source_agent, created_at, updated_at, access_count, last_accessed_at)`
  - 表 `memory_embeddings(memory_id PK, vec BLOB)`
  - 启用 `PRAGMA journal_mode=WAL`，加 `threading.Lock`（与 ontology `SQLiteBackend` 一致）
  - `save_embedding` / `get_embedding` 序列化 `List[float]` 为 BLOB（`struct.pack(f'{len(vec)}f', *vec)`）
- `MemoryStore` 包装：按设计 §4 提供统一接口

**验证**
- `tests/test_memory_storage.py`（参数化三个后端）：
  - upsert → get 还原（embedding 也还原）
  - delete 不存在返回 False
  - all() 返回全量
  - stats() 计数正确
  - SQLite 线程安全（多线程并发 upsert）

---

## M3. 嵌入与检索（`embedder.py` + `index.py`）

**任务**

### `memory/embedder.py`
- `EmbeddingUnavailable(Exception)` 自定义异常
- `Embedder` 类：
  - `__init__(llm=None, enabled=True, cache=None)`
  - `embed_texts(texts: List[str]) -> Optional[List[List[float]]]`：不可用时返回 None；失败抛 `EmbeddingUnavailable`
  - `embed(text: str) -> Optional[List[float]]` 单条封装
  - 缓存：键 = `sha256(text).hexdigest()`，命中即返
  - 实际请求实现：构造 OpenAI 兼容 POST 到 `{base_url.rstrip('/')}/embeddings`，请求体 `{"model": self.llm.model, "input": texts}`，响应取 `data[].embedding`
  - 失败/超时/解析异常 → `EmbeddingUnavailable` 并 `logger.warning`

### `memory/index.py`
- `KeywordIndex`：倒排 `Dict[str, Set[str]]`，`build/update/delete/search`
- 分词：`re.findall(r"[A-Za-z0-9_]+|[一-龥]", text.lower())`
- `search(query, top_n=200)`：词频打分 + 标题（tags）命中加权 ×3
- `HybridRetriever`：
  - `__init__(store, keyword_index, embedder, alpha=0.3)`
  - `recall(query, top_k=5, types=None)`：
    1. 关键词预筛 → 候选 ids
    2. 若 embedder 可用：对候选 `embed` + `embed(query)` 计算余弦；归一化融合 `alpha * kw + (1-alpha) * cos`
    3. 不可用：仅返回关键词打分排序
    4. types 过滤
  - 召回成功后对每条调 `entry.accessed()` 并 `store.upsert()`（更新访问元数据）

**验证**
- `tests/test_memory_retrieval.py`：
  - 关键词命中排序正确（含中英）
  - embedding 可用时融合排序与纯关键词排序不同
  - 关闭 embedder 后降级纯关键词（断言 `embedder.available=False`）
  - types 过滤
  - 召回后 `access_count` 增加

---

## M4. 写入去重

**任务**

在 `memory/manager.py`（或新建 `memory/dedup.py`，推荐独立小模块）实现：
- `find_similar_to_candidate(content, type, store, embedder, threshold=0.92)`：
  1. 用 embedder 算 candidate 向量（不可用则返回 None）
  2. 遍历 store 中同 type 的现有条目
  3. 余弦相似度 ≥ threshold → 返回已有 entry.id
  4. 否则返回 None
- 由 `MemoryManager.remember()` 调用：有相似则 `store.upsert({**old, content: new, updated_at: now})`，否则新增

**验证**
- 单元测试：相同内容二次保存 → `access_count`/`updated_at` 改变但 `id` 不变
- embedder 不可用 → 跳过去重（直接 upsert）

---

## M5. 记忆管理器（`memory/manager.py`）

**任务**

- `MemoryManager` 统一接口：
  ```python
  class MemoryManager:
      def __init__(self, store: MemoryStore, embedder: Embedder, embedder_kw_index: KeywordIndex, retriever: HybridRetriever): ...

      @classmethod
      def from_config(cls, config, llm=None) -> "MemoryManager": ...  # 按 config.memory_backend 选择后端、按 memory_enabled 创建组件

      def remember(self, content, type=MemoryType.FACT, tags=None, importance=0.5, source_session="", source_agent="") -> str:
          """写入一条记忆（去重），返回 entry_id。"""

      def recall(self, query, top_k=5, types=None) -> List[MemoryEntry]: ...

      def forget(self, entry_id) -> bool: ...

      def list(self, types=None, limit=50) -> List[MemoryEntry]: ...

      def stats(self) -> dict: ...
  ```

- `from_config` 流程：
  1. 若 `config.memory_enabled=False` → raise 或返回 None（上层判断）
  2. 探测目录可写性（`Path(config.memory_db_path).parent.mkdir(parents=True, exist_ok=True)`），失败 → `logger.warning` 并 raise
  3. 实例化后端：
     - `sqlite` → `SqliteBackend(config.memory_db_path)`
     - `jsonl` → `JsonlBackend(config.memory_jsonl_path)`
     - `memory` → `InMemoryBackend()`
  4. 构造 `MemoryStore`
  5. 用 store 全量构建 `KeywordIndex`
  6. 构造 `Embedder(llm=llm, enabled=config.memory_embedding_enabled)`
  7. 构造 `HybridRetriever`
  8. 返回 `MemoryManager`

- `remember` 走 §M4 去重；`recall` 走 `HybridRetriever.recall`；`forget` 调 `store.delete` + `kw_index.delete`

**验证**
- `tests/test_memory_manager.py`：
  - `from_config` 各后端构造路径
  - remember → recall 端到端（mock embedder）
  - forget 后 recall 列表不再包含

---

## M6. Agent 集成

**任务**

### `core/agent.py` 改动

1. 在 `Agent.__init__` 中、装配 `OntologyEngine` 之后、`SessionStore` 之前，新增：
   ```python
   from agentorchestra.memory import MemoryManager  # 顶层 import 在文件顶部
   self.memory_manager: Optional[MemoryManager] = None
   if self.config.memory_enabled:
       try:
           self.memory_manager = MemoryManager.from_config(self.config, llm=self.llm)
       except Exception as e:
           self.logger.warning(f"记忆系统未启用（{e}）")
   ```

2. 工具自动注册（在 `SessionStore` 之后）：
   ```python
   if self.memory_manager and self.config.memory_auto_register_tools and self.tool_registry:
       from agentorchestra.memory.tools import MemorySaveTool, MemoryRecallTool
       self.tool_registry.register_tool(MemorySaveTool(self.memory_manager))
       self.tool_registry.register_tool(MemoryRecallTool(self.memory_manager))
   ```

3. 自动回忆注入：在 `arun` 入口附近、`AGENT_START` 之前，添加：
   ```python
   self._memory_inject_prefix: str = ""
   if (self.memory_manager and self.config.memory_auto_recall and input_text):
       try:
           recalled = self.memory_manager.recall(
               input_text, top_k=self.config.memory_recall_top_k)
           if recalled:
               self._memory_inject_prefix = self._format_memory_prefix(recalled)
       except Exception as e:
           self.logger.warning(f"记忆回忆失败: {e}")
   ```

4. 在调 `self.run(...)` 或 `self.arun(...)` 之前，把前缀拼入 system 上下文。可选位置：
   - 方案 A（侵入小）：在 `_build_messages`/`_build_system_prompt` 这类统一点拼接
   - 方案 B（侵入大）：覆盖 `system_prompt` 属性
   - **采用方案 A**：新增 `_effective_system_prompt()` property，在子类构造消息处优先使用

5. 自动总结（默认关闭）：在 `arun` 的 `AGENT_FINISH` 事件之后：
   ```python
   if self.memory_manager and self.config.memory_auto_summarize:
       try:
           await self._auto_memorize(input_text, result)
       except Exception as e:
           self.logger.warning(f"自动总结失败: {e}")
   ```

6. 私有方法：
   - `_format_memory_prefix(entries: List[MemoryEntry]) -> str`：按设计 §7 格式
   - `async _auto_memorize(input_text, result)`：调 `Summarizer.extract(...)` → `manager.remember_batch(...)`

### `memory/tools.py` 新增

- `MemorySaveTool(Tool)` / `MemoryRecallTool(Tool)`：按设计 §6.1 实现，参数严格匹配 `ToolParameter` 协议
- `MemorySaveTool.run`：
  - 解析 `type`（默认 `"fact"`），非法则 `ToolResponse.error(code=INVALID_PARAM, message="...")`
  - `tags` 用 `","` 拆分
  - 调 `manager.remember(...)` → 返回 `ToolResponse.success(text="记忆已保存：<id>", data={...})`
- `MemoryRecallTool.run`：
  - `type` 为空 → 不过滤；非空 → 转 `MemoryType(...)`；非法 → 错误响应
  - 调 `manager.recall(...)` → markdown 列表格式返回

### `memory/summarizer.py` 新增

- `Summarizer(llm)`：
  - `async extract(input_text, history: List[Message], result: str) -> List[MemoryCandidate]`：调轻量 LLM（`temperature=0.2`），要求严格 JSON 输出
  - 解析失败 → `logger.warning` 返回 `[]`
- `MemoryCandidate` dataclass：`type, content, tags, importance`（无 id）
- `_parse_json_response(text)` 容忍 LLM 在 JSON 外加解释文字，用 `re.search(r'\[.*\]', text, re.S)`

**验证**
- `tests/test_memory_agent.py`（mock `SymphonyLLM`）：
  - `memory_enabled=False` → `memory_manager is None`、工具不注册、arun 行为无变化
  - `memory_enabled=True, memory_auto_recall=True` → arun 入口触发 `recall`，`_effective_system_prompt` 包含前缀
  - `memory_auto_recall=False` → 不调用 recall
  - `memory_auto_summarize=True` → arun FINISH 后 `manager.remember_batch` 被调用
  - 注入失败（recall 抛错）→ arun 仍正常返回
- `tests/test_memory_tools.py`：上文中工具端到端

---

## M7. 文档与发布

**任务**

1. `docs/memory/README.md` 新增：API + 用例（与 `docs/skills` / `docs/tools/README.md` 同风格）
2. `docs/README.md` 模块索引加一行：`| [memory](memory/README.md) | 长期记忆系统：跨会话持久记忆 + 混合检索 | 持久化与回忆 |`
3. `docs/README.md` 核心价值列表补一条 `+ **长期记忆**：跨会话持久记忆与混合检索`
4. 根 `README.md` 特性列表补一条：长期记忆
5. 根 `README.md` 目录树补 `memory/`
6. 文档表加 `memory | docs/memory/README.md`
7. （如有 `CHANGELOG.md`）新增条目：v1.x — 长期记忆子系统

**验证**
- 完整跑一遍 5 项 lint/test：
  ```bash
  pytest -q                       # 全 182+ 用例 + 新增
  mypy agentorchestra             # 0 error
  ruff check .                    # 0 error
  ```

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| embedding API 协议差异（Anthropic/Gemini） | v1 只对 OpenAI 兼容 `/embeddings` 协议生效；其他自动降级关键词；文档说明 |
| 大量历史条目时 `iter_all` 构建索引慢 | v1 接受；后续可换增量构建（监听 `upsert/delete`） |
| embedding 缓存无限增长 | v1 LRU 上限 10000 条，`tests` 中验证 |
| 同步 `run()` 不易无侵入挂钩自动总结 | v1 仅在 `arun()` 路径实现自动总结；文档说明 |
| 自动注入前缀污染 system_prompt | 通过 `_effective_system_prompt` 隔离，不修改 HistoryManager；提供 `memory_auto_recall` 关闭 |
