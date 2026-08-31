"""Audit - 审计（对标 Palantir Action log）

记录谁在何时对什么资源执行了什么操作。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


class AuditManager:
    """审计管理器"""

    def __init__(self):
        self._log: List[Dict[str, Any]] = []

    def log(self, principal: str, resource: str, action: str,
            detail: Dict[str, Any] = None, success: bool = True) -> None:
        self._log.append({
            "timestamp": datetime.now().isoformat(),
            "principal": principal,
            "resource": resource,
            "action": action,
            "detail": detail or {},
            "success": success,
        })

    def query(self, principal: Optional[str] = None, resource: Optional[str] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        entries = self._log
        if principal:
            entries = [e for e in entries if e["principal"] == principal]
        if resource:
            entries = [e for e in entries if e["resource"] == resource]
        return list(reversed(entries))[:limit]

    def count(self) -> int:
        return len(self._log)

    def clear(self) -> None:
        self._log.clear()
