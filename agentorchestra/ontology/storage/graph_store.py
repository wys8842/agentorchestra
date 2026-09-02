"""GraphStore - 图存储

存储对象间关系，支持图遍历和传递推理。
对象存储（ObjectStore）用它做链接查询和关系分析。
"""

from typing import Any, Dict, List, Optional


class GraphStore:
    """内存图存储"""

    def __init__(self):
        self._nodes: Dict[str, Dict[str, Any]] = {}   # name -> {label, props}
        self._edges: Dict[str, List[Dict]] = {}       # name -> [{rel, target, props}]

    # ==================== 写入 ====================

    def merge_node(self, label: str, properties: Dict[str, Any],
                   name: Optional[str] = None) -> str:
        """合并节点（存在则更新，不存在则创建）

        Args:
            label: 节点类型标签
            properties: 节点属性（若未提供 name 参数，需含 name 键）
            name: 显式节点名（优先于 properties["name"]）

        Returns:
            节点名
        """
        node_name = name or properties.get("name")
        if not node_name:
            raise ValueError("节点名必须提供（name 参数或 properties 中的 name 键）")

        if node_name not in self._nodes:
            self._nodes[node_name] = {"label": label, "props": dict(properties)}
            self._edges.setdefault(node_name, [])
        else:
            self._nodes[node_name]["label"] = label
            self._nodes[node_name]["props"].update(properties)
        return node_name

    def add_relationship(self, subj: str, rel: str, obj: str,
                         props: Optional[Dict[str, Any]] = None) -> None:
        """创建关系"""
        if subj not in self._nodes:
            self.merge_node("Entity", {"name": subj})
        if obj not in self._nodes:
            self.merge_node("Entity", {"name": obj})
        self._edges.setdefault(subj, []).append({
            "rel": rel, "target": obj, "props": props or {}
        })

    def remove_node(self, name: str) -> bool:
        """删除节点及其所有关联边

        Args:
            name: 节点名称

        Returns:
            True if node existed and was deleted, False otherwise
        """
        if name not in self._nodes:
            return False

        # 删除节点
        self._nodes.pop(name, None)

        # 删除所有指向该节点的边
        for source, edges in list(self._edges.items()):
            self._edges[source] = [e for e in edges if e["target"] != name]

        # 删除该节点发出的所有边
        self._edges.pop(name, None)

        return True

    # ==================== 查询 ====================

    def get_node(self, name: str) -> Optional[Dict[str, Any]]:
        return self._nodes.get(name)

    def get_related(self, node_name: str, rel: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取节点的直接关联"""
        related = []
        for edge in self._edges.get(node_name, []):
            if rel and edge["rel"] != rel:
                continue
            target = self._nodes.get(edge["target"])
            related.append({
                "name": edge["target"],
                "label": target["label"] if target else "Entity",
                "rel": edge["rel"],
                "props": edge["props"],
            })
        return related

    def query_paths(self, start: str, rel: str, max_depth: int = 3,
                    target: Optional[str] = None) -> List[Dict[str, Any]]:
        """路径查询（BFS，支持传递推理）

        Args:
            start: 起始节点
            rel: 关系类型
            max_depth: 最大深度
            target: 目标节点（None 返回所有可达）

        Returns:
            [{"name", "depth", "path"}]
        """
        results = []
        visited = {start}
        queue = [(start, 0, [start])]

        while queue:
            current, depth, path = queue.pop(0)
            if depth >= max_depth:
                continue
            for edge in self._edges.get(current, []):
                if edge["rel"] != rel:
                    continue
                t = edge["target"]
                if t in visited:
                    continue
                visited.add(t)
                new_path = path + [t]
                if target is None or t == target:
                    results.append({"name": t, "depth": depth + 1, "path": new_path})
                    if target is not None:
                        return results
                queue.append((t, depth + 1, new_path))

        return results

    def list_nodes(self) -> List[str]:
        return list(self._nodes.keys())

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return sum(len(e) for e in self._edges.values())

    def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
