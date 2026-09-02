"""QueryEngine - 查询引擎

跨对象类型查询：
- 通过接口查询所有实现类型
- 对象集合操作（过滤/排序/分页）
- 链接导航（从对象沿链接找到关联对象）
"""

from typing import Any, Dict, List, Optional

from .semantic.interface import Interface
from .storage.object_store import ObjectStore


class QueryEngine:
    """查询引擎"""

    def __init__(self, store: ObjectStore):
        self.store = store

    def query_interface(self, interface: Interface,
                        conditions: Optional[Dict[str, Any]] = None,
                        limit: int = 50) -> Dict[str, List[Dict[str, Any]]]:
        """通过接口查询所有实现类型的对象

        Returns:
            {object_type: [objects]}
        """
        results = {}
        for type_name in interface.get_implementations():
            objs = self.store.filter(type_name, conditions or {}) if conditions \
                else self.store.list_objects(type_name)
            results[type_name] = objs[:limit]
        return results

    def navigate_links(self, from_type: str, from_pk: str,
                       link_name: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """从对象沿链接导航（支持多跳）"""
        return self.store.query_links(from_type, from_pk, link_name, max_depth)

    def object_set(self, type_name: str, conditions: Optional[Dict] = None,
                   sort_by: Optional[str] = None, descending: bool = False,
                   limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """对象集合查询（过滤/排序/分页）"""
        objs = self.store.filter(type_name, conditions or {}) if conditions \
            else self.store.list_objects(type_name)

        if sort_by:
            objs = sorted(objs, key=lambda o: o.get(sort_by, ""),
                          reverse=descending)

        total = len(objs)
        page = objs[offset:offset + limit]
        return {"total": total, "offset": offset, "limit": limit, "objects": page}

    def describe_join(self, type_a: str, link_name: str,
                      type_b: str, conditions_a: Optional[Dict] = None) -> List[Dict]:
        """对象 join 查询：从 A 对象沿链接找关联 B 对象"""
        results: List[Dict[str, Any]] = []
        a_type = self.store.get_type(type_a)
        if a_type is None:
            return results
        for a in self.store.list_objects(type_a):
            if conditions_a and not self._matches(a, conditions_a):
                continue
            pk = str(a.get(a_type.primary_key))
            links = self.store.get_links(type_a, pk, link_name)
            for link in links:
                results.append({"from": a, "to": link["object"], "link": link_name})
        return results

    def _matches(self, obj: Dict[str, Any], conditions: Dict[str, Any]) -> bool:
        return all(obj.get(k) == v for k, v in conditions.items())
