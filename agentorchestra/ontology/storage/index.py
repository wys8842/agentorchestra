"""ObjectIndex - 对象索引

提供对象搜索、过滤、聚合能力。
ObjectStore 依赖它做查询优化。

存储通过 BaseStorageBackend 抽象（内存/SQLite），上层无感知。
"""

from typing import Any, Dict, List, Optional

from .backends import BaseStorageBackend, MemoryBackend


class ObjectIndex:
    """对象索引"""

    def __init__(self, backend: Optional[BaseStorageBackend] = None):
        self.backend = backend or MemoryBackend()
        # 反向索引（内存中维护，加速等值过滤）
        self._inverted: Dict[str, Dict[str, Dict[str, set[str]]]] = {}

    @property
    def backend_type(self) -> str:
        return type(self.backend).__name__

    def close(self) -> None:
        self.backend.close()

    # ==================== 维护 ====================

    def register_type(self, type_name: str) -> None:
        self.backend.register_type(type_name)
        self._inverted.setdefault(type_name, {})

    def index_object(self, type_name: str, pk: str, obj: Dict[str, Any]) -> None:
        """索引对象（写操作时调用）"""
        self.backend.put(type_name, pk, obj)

        # 维护反向索引
        inv = self._inverted.setdefault(type_name, {})
        for prop, value in obj.items():
            inv.setdefault(prop, {}).setdefault(str(value), set())
            inv[prop][str(value)].add(pk)

    def update_object(self, type_name: str, pk: str, obj: Dict[str, Any]) -> None:
        self.index_object(type_name, pk, obj)

    def remove_object(self, type_name: str, pk: str) -> Optional[Dict[str, Any]]:
        """删除对象并返回被删对象（不存在返回 None）"""
        obj = self.backend.delete(type_name, pk)
        if obj:
            inv = self._inverted.get(type_name, {})
            for prop, value in obj.items():
                bucket = inv.get(prop, {}).get(str(value))
                if bucket:
                    bucket.discard(pk)
                    if not bucket:
                        del inv[prop][str(value)]
        return obj

    # ==================== 查询 ====================

    def get(self, type_name: str, pk: str) -> Optional[Dict[str, Any]]:
        return self.backend.get(type_name, pk)

    def list(self, type_name: str) -> List[Dict[str, Any]]:
        return self.backend.all(type_name)

    def search(self, type_name: str, query: str,
               fields: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """全文搜索（包含匹配）"""
        if not query:
            return self.list(type_name)

        q = str(query).lower()
        results = []
        for obj in self.backend.all(type_name):
            for field, value in obj.items():
                if fields and field not in fields:
                    continue
                if q in str(value).lower():
                    results.append(obj)
                    break
        return results

    def filter(self, type_name: str, conditions: Dict[str, Any],
               operators: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """条件过滤"""
        results = []
        for obj in self.backend.all(type_name):
            match = True
            for field, expected in conditions.items():
                actual = obj.get(field)
                op = (operators or {}).get(field, "eq")
                if not self._compare(actual, expected, op):
                    match = False
                    break
            if match:
                results.append(obj)
        return results

    def aggregate(self, type_name: str, group_by: str, agg: str = "count",
                  agg_field: Optional[str] = None) -> Dict[str, Any]:
        """聚合统计"""
        groups: Dict[str, Any] = {}
        for obj in self.backend.all(type_name):
            key = obj.get(group_by, "unknown")
            groups.setdefault(key, []).append(obj)

        result = {}
        for key, objs in groups.items():
            if agg == "count":
                result[key] = len(objs)
            elif agg in ("sum", "avg", "min", "max"):
                values = [o.get(agg_field, 0) for o in objs
                          if agg_field in o and isinstance(o.get(agg_field), (int, float))]
                if not values:
                    result[key] = 0
                elif agg == "sum":
                    result[key] = sum(values)
                elif agg == "avg":
                    result[key] = sum(values) / len(values)
                elif agg == "min":
                    result[key] = min(values)
                else:
                    result[key] = max(values)
        return result

    def count(self, type_name: str) -> int:
        return len(self.backend.all(type_name))

    def _compare(self, actual, expected, op: str) -> bool:
        try:
            if op == "eq":
                return actual == expected
            elif op == "ne":
                return actual != expected
            elif op == "gt":
                return actual > expected
            elif op == "gte":
                return actual >= expected
            elif op == "lt":
                return actual < expected
            elif op == "lte":
                return actual <= expected
            elif op == "contains":
                return str(expected) in str(actual)
        except (TypeError, ValueError):
            return False
        return False
