"""Security - 安全

权限规则：定义谁能对什么资源执行什么动作。
"""

from typing import List, Optional


class SecurityContext:
    """安全上下文（谁在操作）"""

    def __init__(self, principal: str = "anonymous", roles: Optional[List[str]] = None):
        self.principal = principal
        self.roles = roles or []

    def has_role(self, role: str) -> bool:
        return role in self.roles


class PermissionRule:
    """权限规则"""

    def __init__(self, resource: str, action: str, roles: List[str]):
        self.resource = resource
        self.action = action
        self.roles = roles

    def allows(self, resource: str, action: str, ctx: SecurityContext) -> bool:
        if self.resource != "*" and self.resource != resource:
            return False
        if self.action != "*" and self.action != action:
            return False
        return any(ctx.has_role(r) for r in self.roles)


class SecurityManager:
    """安全管理器"""

    def __init__(self):
        self._rules: List[PermissionRule] = []

    def add_rule(self, rule: PermissionRule) -> None:
        self._rules.append(rule)

    def allow(self, roles: List[str], resource: str = "*", action: str = "*") -> None:
        self.add_rule(PermissionRule(resource, action, roles))

    def check(self, resource: str, action: str, ctx: SecurityContext) -> bool:
        """权限检查：无规则 = 开放"""
        if not self._rules:
            return True
        return any(rule.allows(resource, action, ctx) for rule in self._rules)
