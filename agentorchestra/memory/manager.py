"""MemoryManager - 跨会话持久记忆的统一入口

职责：
- remember / remember_batch / forget / stats
- 调用：基于 Embedder 做相似度去重
- recall 走 HybridRetriever
- 与存储/索引/embedder 解耦

设计：M4 去重逻辑在此实现：相同内容高相似度 → 更新 updated_at 而非新增。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .embedder import Embedder, EmbeddingUnavailable
from .index import HybridRetriever, KeywordIndex, _cosine
from .models import MemoryEntry, MemoryType
from .storage import (
    BaseMemoryBackend,
    InMemoryBackend,
    JsonlBackend,
    MemoryStore,
    SqliteBackend,
)

logger = logging.getLogger("agentorchestra.memory.manager")


class MemoryManager:
    """记忆系统统一入口。

    用法：
        mgr = MemoryManager.from_config(config, llm=llm)
        eid = mgr.remember(content="用户偏好 X", type=MemoryType.PREFERENCE)
        hits = mgr.recall("用户偏好", top_k=5)
    """

    def __init__(
        self,
        store: MemoryStore,
        embedder: Embedder,
        keyword_index: KeywordIndex,
        retriever: HybridRetriever,
        dedup_threshold: float = 0.92,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.keyword_index = keyword_index
        self.retriever = retriever
        self.dedup_threshold = dedup_threshold

    @classmethod
    def from_config(
        cls,
        config: Any,
        llm: Optional[Any] = None,
    ) -> "MemoryManager":
        """从 Config 与（可选）LLM 实例构造。

        Raises:
            FileNotFoundError / PermissionError: 目录不可写
            ValueError: 配置非法
        """
        backend_name = (getattr(config, "memory_backend", "sqlite") or "sqlite").lower()

        if backend_name == "sqlite":
            db_path = getattr(config, "memory_db_path", "memory/memories.db")
            parent = Path(db_path).parent
            if str(parent) and str(parent) != ".":
                parent.mkdir(parents=True, exist_ok=True)
            backend: BaseMemoryBackend = SqliteBackend(db_path)
        elif backend_name == "jsonl":
            jsonl_path = getattr(config, "memory_jsonl_path", "memory/memories.jsonl")
            parent = Path(jsonl_path).parent
            if str(parent) and str(parent) != ".":
                parent.mkdir(parents=True, exist_ok=True)
            backend = JsonlBackend(jsonl_path)
        elif backend_name == "memory":
            backend = InMemoryBackend()
        else:
            raise ValueError(f"未知的 memory_backend: {backend_name}")

        store = MemoryStore(backend)
        embed_enabled = bool(getattr(config, "memory_embedding_enabled", True))
        embedder = Embedder(llm=llm, enabled=embed_enabled)
        keyword_index = KeywordIndex()
        keyword_index.build(store.iter_all())
        retriever = HybridRetriever(store, keyword_index, embedder=embedder)
        dedup = float(getattr(config, "memory_dedup_threshold", 0.92))
        return cls(
            store=store,
            embedder=embedder,
            keyword_index=keyword_index,
            retriever=retriever,
            dedup_threshold=dedup,
        )

    # ==================== 写入 ====================

    def remember(
        self,
        content: str,
        type: MemoryType = MemoryType.FACT,
        tags: Optional[List[str]] = None,
        importance: float = 0.5,
        source_session: str = "",
        source_agent: str = "",
    ) -> str:
        """写入一条记忆（含去重）。

        Args:
            content: 文本内容
            type: 记忆类型
            tags: 标签列表
            importance: 重要性 0~1
            source_session / source_agent: 元数据

        Returns:
            条目 ID（新写入或已更新）
        """
        if not content or not content.strip():
            raise ValueError("content 不能为空")

        entry = MemoryEntry(
            type=type,
            content=content.strip(),
            tags=list(tags or []),
            importance=float(importance),
            source_session=source_session,
            source_agent=source_agent,
        )

        # 去重（仅在 embedding 可用时启用）
        existing_id = self._find_similar_existing(entry)
        if existing_id is not None:
            old = self.store.get(existing_id)
            if old is not None:
                # 合并：保留旧 id，更新内容/tags/touch；importance 取 max
                old.content = entry.content
                if entry.tags:
                    old.tags = sorted(set(old.tags) | set(entry.tags))
                old.importance = max(old.importance, entry.importance)
                old.touch()
                self._save_with_embedding(old)
                return old.id

        # 新增
        self._save_with_embedding(entry)
        return entry.id

    def remember_batch(self, candidates: List[Dict[str, Any]]) -> List[str]:
        """批量写入候选记忆（自动总结使用）。

        Args:
            candidates: [{"content": ..., "type": ..., "tags": [...], "importance": ...}, ...]

        Returns:
            写入成功的 entry id 列表
        """
        ids: List[str] = []
        for c in candidates:
            try:
                type_val = c.get("type", MemoryType.FACT)
                if isinstance(type_val, str):
                    try:
                        type_val = MemoryType(type_val)
                    except ValueError:
                        type_val = MemoryType.FACT
                eid = self.remember(
                    content=c.get("content", ""),
                    type=type_val,
                    tags=c.get("tags", []),
                    importance=float(c.get("importance", 0.5)),
                )
                ids.append(eid)
            except Exception as e:
                logger.warning(f"remember_batch 单条失败: {e}")
        return ids

    def _find_similar_existing(self, candidate: MemoryEntry) -> Optional[str]:
        """若新条目与已有条目相似度 ≥ 阈值，返回已有 id；否则 None。"""
        if not (self.embedder.available):
            return None
        try:
            vec = self.embedder.embed(candidate.content)
        except EmbeddingUnavailable:
            return None
        except Exception as e:
            logger.debug(f"去重 embedding 失败，跳过: {e}")
            return None
        if vec is None:
            return None
        best_id: Optional[str] = None
        best_score = 0.0
        for existing in self.store.iter_all():
            if existing.type != candidate.type:
                continue
            ev = existing.embedding
            if ev is None:
                continue
            score = _cosine(vec, ev)
            if score >= self.dedup_threshold and score > best_score:
                best_score = score
                best_id = existing.id
        return best_id

    def _save_with_embedding(self, entry: MemoryEntry) -> None:
        """写入 entry + 若 embedder 可用则算 embedding 同步落盘 + 索引更新。"""
        if self.embedder.available and entry.embedding is None:
            try:
                vec = self.embedder.embed(entry.content)
                if vec is not None:
                    entry.embedding = vec
                    try:
                        self.store.backend.save_embedding(entry.id, vec)
                    except Exception as e:
                        logger.debug(f"embedding 落盘失败: {e}")
            except EmbeddingUnavailable:
                pass
            except Exception as e:
                logger.debug(f"去重 embedding 失败，跳过: {e}")
        self.store.upsert(entry)
        self.keyword_index.update(entry)

    # ==================== 检索 ====================

    def recall(
        self,
        query: str,
        top_k: int = 5,
        types: Optional[List[MemoryType]] = None,
    ) -> List[MemoryEntry]:
        """按 query 召回相关记忆条目。"""
        return self.retriever.recall(query, top_k=top_k, types=types)

    def list(
        self,
        types: Optional[List[MemoryType]] = None,
        limit: int = 50,
    ) -> List[MemoryEntry]:
        """列出记忆条目（按 updated_at 倒序）。"""
        types_set = None
        if types:
            types_set = {t.value if isinstance(t, MemoryType) else str(t) for t in types}
        items: List[MemoryEntry] = []
        for entry in self.store.iter_all():
            if types_set is not None:
                t_val = entry.type.value if isinstance(entry.type, MemoryType) else str(entry.type)
                if t_val not in types_set:
                    continue
            items.append(entry)
        items.sort(key=lambda e: e.updated_at, reverse=True)
        return items[:limit]

    # ==================== 删除/统计 ====================

    def forget(self, entry_id: str) -> bool:
        ok = self.store.delete(entry_id)
        if ok:
            self.keyword_index.delete(entry_id)
        return ok

    def stats(self) -> Dict[str, Any]:
        return {
            "store": self.store.stats(),
            "dedup_threshold": self.dedup_threshold,
            "embedder_available": self.embedder.available,
        }

    def close(self) -> None:
        try:
            self.store.close()
        except Exception:
            pass
