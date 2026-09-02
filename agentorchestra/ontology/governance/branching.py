"""Branching - 分支

对象存储的快照/回滚/分支版本。
"""

from datetime import datetime
from typing import Any, Dict, List


class Branch:
    """对象存储的一个分支版本"""

    def __init__(self, name: str, snapshot: Dict[str, Any]):
        self.name = name
        self.snapshot = snapshot
        self.created_at = datetime.now().isoformat()


class BranchManager:
    """分支管理器"""

    def __init__(self):
        self._branches: Dict[str, Branch] = {}
        self._active = "main"

    def create_branch(self, name: str, store) -> Branch:
        """创建分支（当前状态快照）"""
        branch = Branch(name, self._snapshot_store(store))
        self._branches[name] = branch
        return branch

    def list_branches(self) -> List[str]:
        return list(self._branches.keys())

    def get_active(self) -> str:
        return self._active

    def switch_to(self, name: str, store) -> bool:
        """切换分支（回滚 store 到该分支快照）"""
        branch = self._branches.get(name)
        if not branch:
            return False
        self._restore_store(store, branch.snapshot)
        self._active = name
        return True

    def merge_to(self, name: str, store) -> bool:
        """将分支内容回滚到 main（实质是恢复快照，非真正合并）

        注意：此方法将指定分支的快照恢复到 main 对象，
        不会保留分支的增量变更。相当于"回滚"而非"合并"。

        Args:
            name: 分支名称
            store: ObjectStore 实例

        Returns:
            是否成功
        """
        branch = self._branches.get(name)
        if not branch:
            return False
        self._restore_store(store, branch.snapshot)
        self._active = "main"
        return True

    def delete_branch(self, name: str) -> bool:
        if name in self._branches:
            del self._branches[name]
            return True
        return False

    # ==================== 快照 ====================

    def _snapshot_store(self, store) -> Dict[str, Any]:
        """从 ObjectStore 创建快照"""
        snapshot = {"objects": {}, "types": {}, "active": self._active}
        for type_name in store.list_types():
            objs = store.list_objects(type_name)
            snapshot["objects"][type_name] = {
                str(o.get(store.get_type(type_name).primary_key, i)): dict(o)
                for i, o in enumerate(objs)
            }
        return snapshot

    def _restore_store(self, store, snapshot: Dict[str, Any]) -> None:
        """把快照恢复到 ObjectStore"""
        from ..storage.object_store import ObjectStore
        if not isinstance(store, ObjectStore):
            return
        # 清空现有对象
        for type_name in store.list_types():
            obj_type = store.get_type(type_name)
            if obj_type is None:
                continue
            for obj in store.list_objects(type_name):
                pk = obj.get(obj_type.primary_key)
                if pk is not None:
                    store.delete(type_name, str(pk))
        # 恢复快照对象
        for type_name, objs in snapshot.get("objects", {}).items():
            for pk, obj in objs.items():
                try:
                    store.insert(type_name, obj)
                except Exception:
                    pass
