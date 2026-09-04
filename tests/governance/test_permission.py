"""PermissionChecker 测试：无权 → PermissionDenied；RBAC+ACL 组合。"""

import pytest

from agentorchestra.governance import ACLManager, PermissionChecker, PermissionDenied
from agentorchestra.ontology.governance.security import (
    SecurityManager,
)


def _security_with_admin():
    """RBAC：admin 全权，viewer 只读 module。"""
    sec = SecurityManager()
    sec.allow(["admin"], resource="*", action="*")
    sec.allow(["viewer"], resource="Order", action="read")
    return sec


def _security_viewer_can_write_order():
    """RBAC：viewer 可写 Order（类型级），行级由 ACL 再约束。"""
    sec = SecurityManager()
    sec.allow(["admin"], resource="*", action="*")
    sec.allow(["viewer"], resource="Order", action="*")
    return sec


def test_deny_raises_permission_denied():
    sec = _security_with_admin()
    pc = PermissionChecker(security=sec)
    with pytest.raises(PermissionDenied):
        pc.check("Order", "write", principal="viewer", roles=["viewer"])
    # raise_on_deny=False → 返回 False
    assert pc.check("Order", "write", principal="viewer", roles=["viewer"],
                    raise_on_deny=False) is False


def test_admin_allowed():
    sec = _security_with_admin()
    pc = PermissionChecker(security=sec)
    assert pc.check("Order", "write", principal="root", roles=["admin"]) is True


def test_acl_row_level_adds_restriction():
    """RBAC 允许但 ACL（行级）拒绝 → 无权。"""
    sec = _security_viewer_can_write_order()  # viewer 类型级可写 Order
    acl = ACLManager()
    acl.grant("Order:o1", "write", principal="alice")
    pc = PermissionChecker(security=sec, acl=acl)
    # viewer 无 obj_id → RBAC 放行
    assert pc.check("Order", "write", roles=["viewer"]) is True
    # viewer 改 o1 但 o1 ACL 只给 alice → 拒绝
    with pytest.raises(PermissionDenied):
        pc.check("Order", "write", roles=["viewer"], obj_id="o1")


def test_acl_grants_specific_row():
    sec = _security_viewer_can_write_order()
    acl = ACLManager()
    acl.grant("Order:o1", "write", principal="alice")
    pc = PermissionChecker(security=sec, acl=acl)
    assert pc.check("Order", "write", principal="alice",
                    roles=["viewer"], obj_id="o1") is True
    # bob 无 o1 ACL → 拒绝
    with pytest.raises(PermissionDenied):
        pc.check("Order", "write", principal="bob", roles=["viewer"], obj_id="o1")


def test_no_security_no_acl_allows():
    """最小可用：未装配权限 → 放行。"""
    pc = PermissionChecker()
    assert pc.check("Order", "write") is True


def test_security_only_no_obj_id_allows_row():
    """RBAC 允许 + 无 ACL（obj_id 给定但 acl=None）→ 放行。"""
    sec = _security_with_admin()
    pc = PermissionChecker(security=sec)
    assert pc.check("Order", "read", roles=["viewer"], obj_id="o1") is True
    # viewer 无 write → PermissionDenied
    with pytest.raises(PermissionDenied):
        pc.check("Order", "write", roles=["viewer"], obj_id="o1")
