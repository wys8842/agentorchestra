"""关键词倒排索引 + 混合检索器

- KeywordIndex: 倒排索引构建/更新/删除/查询
- HybridRetriever: 关键词预筛 + 余弦精排融合

分词策略（无外部依赖）：re.findall(r"[A-Za-z0-9_]+|[一-龥]", text.lower())
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .embedder import Embedder, EmbeddingUnavailable
from .models import MemoryEntry, MemoryType
from .storage import MemoryStore

logger = logging.getLogger("agentorchestra.memory.index")

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-龥]")
_TAG_WEIGHT = 3.0  # 标签命中权重（相对正文命中 1.0）


def _tokenize(text: str) -> List[str]:
    """简单中英混合分词（小写）。"""
    return _TOKEN_RE.findall((text or "").lower())


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """余弦相似度（两个非零向量）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class KeywordIndex:
    """倒排索引（词 → 文档 id → 命中次数）。

    内存构建，由 MemoryManager 启动时调用 build() 初始化，upsert/delete 时增量更新。
    """

    def __init__(self) -> None:
        # token -> {doc_id -> count}
        self._index: Dict[str, Dict[str, int]] = {}
        # doc_id -> 总分（用于快速返回）
        self._doc_tokens: Dict[str, Counter] = {}

    def build(self, entries: Iterable[MemoryEntry]) -> None:
        self._index.clear()
        self._doc_tokens.clear()
        for entry in entries:
            self.update(entry)

    def update(self, entry: MemoryEntry) -> None:
        doc_id = entry.id
        # 删除旧的 token 记录
        self.delete(doc_id)
        tokens = _tokenize(entry.content)
        tag_tokens = _tokenize(" ".join(entry.tags))
        counter: Counter = Counter()
        for t in tokens:
            counter[t] += 1
        for t in tag_tokens:
            counter[t] += int(_TAG_WEIGHT)  # 标签加权
        if not counter:
            return
        for t, c in counter.items():
            self._index.setdefault(t, {})[doc_id] = c
        self._doc_tokens[doc_id] = counter

    def delete(self, doc_id: str) -> None:
        counter = self._doc_tokens.pop(doc_id, None)
        if not counter:
            return
        for t in counter:
            bucket = self._index.get(t)
            if bucket and doc_id in bucket:
                del bucket[doc_id]
                if not bucket:
                    del self._index[t]

    def search(self, query: str, top_n: int = 200) -> List[Tuple[str, float]]:
        """返回 (doc_id, score) 列表，按 score 降序，长度 ≤ top_n。"""
        tokens = _tokenize(query)
        if not tokens:
            return []
        scores: Dict[str, float] = {}
        for t in tokens:
            bucket = self._index.get(t)
            if not bucket:
                continue
            for doc_id, count in bucket.items():
                scores[doc_id] = scores.get(doc_id, 0.0) + float(count)
        if not scores:
            return []
        sorted_items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return sorted_items[:top_n]


class HybridRetriever:
    """混合检索器：关键词预筛 + 向量精排 + 融合。

    流程：
    1. 关键词预筛 → 候选 doc_ids（≤ top_n）
    2. Embedder 可用：对候选算相似度，归一化融合 α * kw + (1-α) * cos
       不可用：返回关键词排序结果
    3. 类型过滤 + 取 top_k
    """

    def __init__(
        self,
        store: MemoryStore,
        keyword_index: KeywordIndex,
        embedder: Optional[Embedder] = None,
        alpha: float = 0.3,
    ) -> None:
        self.store = store
        self.keyword_index = keyword_index
        self.embedder = embedder
        self.alpha = alpha

    def recall(
        self,
        query: str,
        top_k: int = 5,
        types: Optional[List[MemoryType]] = None,
    ) -> List[MemoryEntry]:
        if not query:
            return []

        # 1. 关键词预筛
        kw_candidates = self.keyword_index.search(query, top_n=200)
        if not kw_candidates:
            return []

        # 2. 类型过滤
        if types:
            types_set = {t.value if isinstance(t, MemoryType) else str(t) for t in types}
            filtered: List[Tuple[str, float]] = []
            for doc_id, score in kw_candidates:
                entry = self.store.get(doc_id)
                if entry is None:
                    continue
                t_val = entry.type.value if isinstance(entry.type, MemoryType) else str(entry.type)
                if t_val in types_set:
                    filtered.append((doc_id, score))
            kw_candidates = filtered

        if not kw_candidates:
            return []

        # 3. 向量精排（如可用）
        use_embedder = self.embedder is not None and self.embedder.available
        cos_scores: Dict[str, float] = {}
        if use_embedder and self.embedder is not None:
            try:
                query_vec = self.embedder.embed(query)
            except EmbeddingUnavailable:
                use_embedder = False
                logger.debug("Embedding 不可用，降级为关键词检索")
            except Exception as e:
                use_embedder = False
                logger.warning(f"Embedding 失败，降级: {e}")

            if use_embedder and query_vec is not None:
                for doc_id, _ in kw_candidates:
                    entry = self.store.get(doc_id)
                    if entry is None or not entry.embedding:
                        continue
                    cos_scores[doc_id] = _cosine(query_vec, entry.embedding)

        # 4. 融合归一化
        if cos_scores:
            kw_scores_only = [s for _, s in kw_candidates]
            kw_max = max(kw_scores_only) if kw_scores_only else 1.0
            kw_min = min(kw_scores_only) if kw_scores_only else 0.0
            cos_vals = list(cos_scores.values())
            cos_max = max(cos_vals) if cos_vals else 1.0
            cos_min = min(cos_vals) if cos_vals else 0.0

            def normalize(v: float, lo: float, hi: float) -> float:
                if hi == lo:
                    return 1.0 if v == hi else 0.0
                return (v - lo) / (hi - lo)

            fused: List[Tuple[str, float]] = []
            for doc_id, kw_s in kw_candidates:
                cos_s = cos_scores.get(doc_id)
                if cos_s is None:
                    fused.append((doc_id, normalize(kw_s, kw_min, kw_max)))
                else:
                    score = self.alpha * normalize(kw_s, kw_min, kw_max) + \
                             (1.0 - self.alpha) * normalize(cos_s, cos_min, cos_max)
                    fused.append((doc_id, score))
        else:
            # 仅关键词：直接用分数
            fused = [(doc_id, float(s)) for doc_id, s in kw_candidates]

        fused.sort(key=lambda kv: kv[1], reverse=True)

        # 5. 取 top_k
        result: List[MemoryEntry] = []
        for doc_id, _score in fused[:top_k]:
            entry = self.store.get(doc_id)
            if entry is None:
                continue
            entry.accessed()
            # 同步访问元数据
            try:
                self.store.upsert(entry)
            except Exception as e:
                logger.debug(f"访问元数据更新失败: {e}")
            result.append(entry)
        return result
