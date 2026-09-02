"""Materialization - 物化

把对象编辑结果回写到数据源，形成"编辑 → 物化"闭环。
支持注册自定义数据源回写函数。
"""

from typing import Any, Callable, Dict, List, Optional


class MaterializationTarget:
    """物化目标（数据源回写目标）"""

    def __init__(self, name: str, write_fn: Callable):
        """定义物化目标

        Args:
            name: 目标名（如 "postgres_orders"）
            write_fn: 回写函数 fn(operation, type_name, obj, patch) -> bool
                operation: "insert"/"update"/"delete"
        """
        self.name = name
        self.write_fn = write_fn

    def write(self, operation: str, type_name: str,
              obj: Dict[str, Any], patch: Optional[Dict] = None) -> bool:
        return self.write_fn(operation, type_name, obj, patch)


class MaterializationManager:
    """物化管理器"""

    def __init__(self):
        self._targets: Dict[str, MaterializationTarget] = {}
        self._log: List[Dict[str, Any]] = []

    def register_target(self, target: MaterializationTarget) -> None:
        self._targets[target.name] = target

    def materialize(self, operation: str, type_name: str,
                    obj: Dict[str, Any], patch: Optional[Dict] = None,
                    target_name: Optional[str] = None) -> List[bool]:
        """执行物化（写回目标数据源）"""
        results = []
        targets = ([self._targets[target_name]] if target_name
                   else list(self._targets.values()))

        for target in targets:
            try:
                ok = target.write(operation, type_name, obj, patch)
                self._log.append({
                    "target": target.name,
                    "operation": operation,
                    "type": type_name,
                    "pk": obj.get("pk") if obj else None,
                    "success": ok,
                })
                results.append(ok)
            except Exception as e:
                self._log.append({
                    "target": target.name,
                    "operation": operation,
                    "type": type_name,
                    "success": False,
                    "error": str(e),
                })
                results.append(False)

        return results

    def get_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(reversed(self._log))[:limit]

    def clear_log(self) -> None:
        self._log.clear()
