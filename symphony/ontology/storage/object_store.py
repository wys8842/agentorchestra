"""ObjectStore - 对象存储（对标 Palantir Object Storage V2）

组合对象索引（ObjectIndex）和关系图（GraphStore）：
- 对象写入带类型校验（复用 ObjectType.validate_object）
- 索引支持搜索/过滤/聚合
- 图支持链接查询/路径遍历
"""

from typing import Any, Dict, List, Optional

from ..semantic.object_type import ObjectType
from .backends import MemoryBackend, StorageBackend
from .graph_store import GraphStore
from .index import ObjectIndex


class ObjectStore:
    """对象存储"""

    def __init__(self, graph: Optional[GraphStore] = None,
                 backend: Optional[StorageBackend] = None):
        """初始化对象存储

        Args:
            graph: 图存储（关系/路径查询）
            backend: 存储后端（默认内存；传 SQLiteBackend 实现持久化）
        """
        self.index = ObjectIndex(backend=backend or MemoryBackend())
        self.graph = graph or GraphStore()
        self._types: Dict[str, ObjectType] = {}

    @property
    def backend_type(self) -> str:
        """当前存储后端类型"""
        return self.index.backend_type

    def close(self) -> None:
        """关闭存储后端"""
        self.index.close()

    # ==================== 类型注册 ====================

    def register_type(self, object_type: ObjectType) -> None:
        self._types[object_type.api_name] = object_type
        self.index.register_type(object_type.api_name)

    def get_type(self, api_name: str) -> Optional[ObjectType]:
        return self._types.get(api_name)

    def list_types(self) -> List[str]:
        return list(self._types.keys())

    # ==================== 对象写入 ====================

    def insert(self, type_name: str, obj: Dict[str, Any]) -> Dict[str, Any]:
        """插入对象（校验主键/必填/类型/派生属性）"""
        obj_type = self._require_type(type_name)

        errors = obj_type.validate_object(obj)
        if errors:
            raise ValueError(f"对象校验失败: {errors}")

        # 拒绝写入派生属性（值由 Function 计算）
        derived_written = [p for p in obj if obj_type.is_derived(p)]
        if derived_written:
            raise ValueError(f"派生属性不可直接写入: {derived_written}")

        pk = str(obj[obj_type.primary_key])

        # 补充默认值
        for p in obj_type.get_properties():
            if p.name not in obj and p.default is not None:
                obj[p.name] = p.default

        self.index.index_object(type_name, pk, obj)

        # 同步图节点（显式 name，避免与业务字段 name 冲突）
        self.graph.merge_node(
            obj_type.api_name, dict(obj), name=f"{type_name}:{pk}")

        return self.index.get(type_name, pk)

    def update(self, type_name: str, pk: str, patch: Dict[str, Any]) -> Dict[str, Any]:
        """更新对象（部分字段，合并后重新校验）"""
        obj_type = self._require_type(type_name)
        pk = str(pk)

        if obj_type.primary_key in patch:
            raise ValueError(f"主键 {obj_type.primary_key} 不可更新")

        # 拒绝写入派生属性
        derived_written = [p for p in patch if obj_type.is_derived(p)]
        if derived_written:
            raise ValueError(f"派生属性不可直接写入: {derived_written}")

        current = self.index.get(type_name, pk)
        if not current:
            raise ValueError(f"对象不存在: {type_name}/{pk}")

        merged = dict(current)
        merged.update(patch)

        # 合并后重新校验（未知属性/类型/必填）
        errors = obj_type.validate_object(merged)
        if errors:
            raise ValueError(f"对象校验失败: {errors}")

        self.index.update_object(type_name, pk, merged)
        self.graph.merge_node(
            obj_type.api_name, dict(merged), name=f"{type_name}:{pk}")
        return merged

    def delete(self, type_name: str, pk: str) -> bool:
        pk = str(pk)
        removed = self.index.remove_object(type_name, pk)
        if removed:
            # 清理图节点（含 type:pk 和裸 pk 两种命名）
            self.graph._nodes.pop(f"{type_name}:{pk}", None)
            self.graph._nodes.pop(pk, None)
            self.graph._edges.pop(f"{type_name}:{pk}", None)
            self.graph._edges.pop(pk, None)
        return removed is not None

    # ==================== 对象读取 ====================

    def get(self, type_name: str, pk: str) -> Optional[Dict[str, Any]]:
        return self.index.get(type_name, str(pk))

    def list_objects(self, type_name: str) -> List[Dict[str, Any]]:
        return self.index.list(type_name)

    def search(self, type_name: str, query: str,
               fields: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        return self.index.search(type_name, query, fields)

    def filter(self, type_name: str, conditions: Dict[str, Any],
               operators: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        return self.index.filter(type_name, conditions, operators)

    def aggregate(self, type_name: str, group_by: str, agg: str = "count",
                  agg_field: Optional[str] = None) -> Dict[str, Any]:
        return self.index.aggregate(type_name, group_by, agg, agg_field)

    def count(self, type_name: str) -> int:
        return self.index.count(type_name)

    # ==================== 链接 ====================

    def create_link(self, from_type: str, from_pk: str, link_name: str,
                    to_type: str, to_pk: str) -> None:
        """创建对象链接"""
        from_pk, to_pk = str(from_pk), str(to_pk)

        if not self.get(from_type, from_pk):
            raise ValueError(f"源对象不存在: {from_type}/{from_pk}")
        if not self.get(to_type, to_pk):
            raise ValueError(f"目标对象不存在: {to_type}/{to_pk}")

        # 关系校验：链接类型必须存在，且两端类型匹配（含子类继承）
        self._validate_link(from_type, link_name, to_type)

        self.graph.add_relationship(
            f"{from_type}:{from_pk}", link_name.upper(), f"{to_type}:{to_pk}",
            {"source": "object_store", "confidence": 1.0})

    def _validate_link(self, from_type: str, link_name: str, to_type: str) -> None:
        """校验链接类型：存在性 + 两端类型匹配（domain/range，含子类继承）"""
        from_type_def = self._require_type(from_type)
        to_type_def = self._require_type(to_type)

        link = from_type_def.get_link_type(link_name)
        if not link:
            raise ValueError(
                f"链接 '{link_name}' 未在对象类型 '{from_type}' 中定义")

        # from 端校验
        if link.from_type != from_type:
            # 允许子类（from_type 是 link.from_type 的子类）
            if not (from_type_def.is_subclass_of(link.from_type, self._types) or
                    link.from_type == from_type):
                raise ValueError(
                    f"链接 '{link_name}' 的源类型应为 {link.from_type}，实际 {from_type}")

        # to 端校验
        if link.to_type != to_type:
            if not (to_type_def.is_subclass_of(link.to_type, self._types) or
                    link.to_type == to_type):
                raise ValueError(
                    f"链接 '{link_name}' 的目标类型应为 {link.to_type}，实际 {to_type}")

    def get_subclasses(self, type_name: str, transitive: bool = True) -> List[str]:
        """获取对象类型的子类型（类层次查询）"""
        direct = [t for t, d in self._types.items()
                  if d.parent_type == type_name]
        result = list(direct)
        if transitive:
            for sub in direct:
                for deeper in self.get_subclasses(sub, transitive=True):
                    if deeper not in result:
                        result.append(deeper)
        return result

    def get_superclasses(self, type_name: str) -> List[str]:
        """获取对象类型的父类型链（含多级）"""
        chain = []
        current = self._types.get(type_name)
        visited = set()
        while current and current.parent_type:
            if current.parent_type in visited:
                break
            visited.add(current.parent_type)
            chain.append(current.parent_type)
            current = self._types.get(current.parent_type)
        return chain

    def get_links(self, from_type: str, from_pk: str,
                  link_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """查询对象链接"""
        from_pk = str(from_pk)
        related = self.graph.get_related(f"{from_type}:{from_pk}",
                                         link_name.upper() if link_name else None)
        results = []
        for r in related:
            to_type, _, to_pk = r["name"].partition(":")
            results.append({
                "to_type": to_type,
                "to_pk": to_pk,
                "link_name": r["rel"].lower(),
                "object": self.get(to_type, to_pk),
            })
        return results

    def query_links(self, from_type: str, from_pk: str, link_name: str,
                    max_depth: int = 3) -> List[Dict[str, Any]]:
        """跨链接路径查询（传递推理）"""
        paths = self.graph.query_paths(
            f"{from_type}:{from_pk}", link_name.upper(), max_depth)
        results = []
        for p in paths:
            to_type, _, to_pk = p["name"].partition(":")
            results.append({
                "to_type": to_type,
                "to_pk": to_pk,
                "depth": p["depth"],
                "path": p["path"],
                "object": self.get(to_type, to_pk),
            })
        return results

    # ==================== 工具 ====================

    def _require_type(self, type_name: str) -> ObjectType:
        obj_type = self._types.get(type_name)
        if not obj_type:
            raise ValueError(f"对象类型不存在: {type_name}")
        return obj_type

    def stats(self) -> Dict[str, Any]:
        return {
            "types": len(self._types),
            "objects": {t: self.index.count(t) for t in self._types},
            "nodes": self.graph.node_count(),
            "edges": self.graph.edge_count(),
        }
