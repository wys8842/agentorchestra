"""TransactionManager - 事务管理器（动作原子性/补偿）

保证一组动作要么全部成功，要么通过补偿动作回滚：
- 记录每个动作的补偿动作（undo）
- 动作失败时，逆序执行已成功动作的补偿
- 支持保存点（savepoint）部分提交
- 提供事务日志

补偿模式（Saga）：
  动作A(成功) → 动作B(成功) → 动作C(失败)
    ↓ 回滚
  补偿C(跳过) → 补偿B → 补偿A  → 状态恢复
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


class CompensatingAction:
    """带补偿的动作定义"""

    def __init__(self, name: str, action_fn: Callable, compensate_fn: Optional[Callable]):
        """定义可补偿动作

        Args:
            name: 动作名
            action_fn: 执行函数 fn(params, ctx) -> result
            compensate_fn: 补偿函数 fn(params, ctx)（撤销 action_fn 的效果）
        """
        self.name = name
        self.action_fn = action_fn
        self.compensate_fn = compensate_fn


class TransactionManager:
    """事务管理器"""

    def __init__(self):
        self._actions: Dict[str, CompensatingAction] = {}
        self._tx_log: List[Dict[str, Any]] = []

    def register_action(self, action: CompensatingAction) -> None:
        """注册可补偿动作"""
        self._actions[action.name] = action

    def register(self, name: str, action_fn: Callable,
                 compensate_fn: Optional[Callable] = None) -> CompensatingAction:
        """便捷注册动作"""
        action = CompensatingAction(name, action_fn, compensate_fn)
        self._actions[name] = action
        return action

    def get_action(self, name: str) -> Optional[CompensatingAction]:
        return self._actions.get(name)

    # ==================== 事务执行 ====================

    def execute(self, steps: List[Dict[str, Any]],
                ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行事务（Saga 补偿）

        Args:
            steps: [{"action": "扣库存", "params": {...}}, ...]
                按顺序执行；任一失败则逆序补偿已成功的
            ctx: 执行上下文

        Returns:
            {"success", "completed": [动作名], "failed": 失败动作,
             "compensated": [已补偿动作名], "errors"}
        """
        ctx = ctx or {}
        completed: List[str] = []
        completed_params: Dict[str, Dict] = {}  # 动作名 -> 原参数（供补偿）
        tx_record = {
            "started_at": datetime.now().isoformat(),
            "steps": [s.get("action") for s in steps],
            "completed": [],
            "failed": None,
            "compensated": [],
            "errors": [],
        }

        # ① 正序执行
        for step in steps:
            action_name = step.get("action")
            action = self._actions.get(action_name)
            if not action:
                # 未注册动作视为失败：触发已成功动作的补偿
                tx_record["failed"] = action_name
                tx_record["errors"].append(f"动作未注册: {action_name}")
                break

            step_params = step.get("params", {})
            try:
                action.action_fn(step_params, ctx)
                completed.append(action_name)
                completed_params[action_name] = step_params
                tx_record["completed"].append(action_name)
            except Exception as e:
                tx_record["failed"] = action_name
                tx_record["errors"].append(f"动作 '{action_name}' 失败: {e}")
                break

        # ② 若失败，逆序补偿
        if tx_record["failed"]:
            for name in reversed(completed):
                action = self._actions.get(name)
                if action and action.compensate_fn:
                    try:
                        action.compensate_fn(completed_params.get(name, {}), ctx)
                        tx_record["compensated"].append(name)
                    except Exception as e:
                        tx_record["errors"].append(f"补偿 '{name}' 失败: {e}")
                elif action and not action.compensate_fn:
                    tx_record["errors"].append(f"动作 '{name}' 无补偿，无法回滚")

        tx_record["success"] = not tx_record["failed"]
        tx_record["ended_at"] = datetime.now().isoformat()
        self._tx_log.append(tx_record)
        return tx_record

    # ==================== 保存点 ====================

    def savepoint(self, name: str, store) -> Dict[str, Any]:
        """创建保存点（快照当前状态）"""
        from ..storage.object_store import ObjectStore
        snapshot = {"objects": {}}
        if isinstance(store, ObjectStore):
            for t in store.list_types():
                snapshot["objects"][t] = list(store.list_objects(t))
        return {"name": name, "snapshot": snapshot}

    def rollback_to(self, savepoint: Dict[str, Any], store) -> bool:
        """回滚到保存点"""
        from ..storage.object_store import ObjectStore
        if not isinstance(store, ObjectStore):
            return False
        try:
            for t in store.list_types():
                for obj in store.list_objects(t):
                    pk = obj.get(store.get_type(t).primary_key)
                    if pk is not None:
                        store.delete(t, str(pk))
            for t, objs in savepoint.get("snapshot", {}).get("objects", {}).items():
                for obj in objs:
                    try:
                        store.insert(t, dict(obj))
                    except Exception:
                        pass
            return True
        except Exception:
            return False

    # ==================== 查询 ====================

    def get_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """查询事务日志"""
        return list(reversed(self._tx_log))[:limit]

    def clear_log(self) -> None:
        self._tx_log.clear()
