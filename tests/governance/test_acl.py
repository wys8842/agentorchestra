"""ACL 测试：grant/revoke/check（精确 + 通配 + principal/role）。"""

from agentorchestra.governance import ACLManager


def test_grant_exact_principal():
    acl = ACLManager()
    acl.grant("order:o1", "write", principal="alice")
    assert acl.check("order:o1", "write", principal="alice") is True
    assert acl.check("order:o1", "write", principal="bob") is False


def test_grant_role():
    acl = ACLManager()
    acl.grant("order:*", "read", role="finance")
    assert acl.check("order:o99", "read", roles=["finance"]) is True
    assert acl.check("order:o99", "read", roles=["viewer"]) is False


def test_wildcard_resource():
    acl = ACLManager()
    acl.grant("order:*", "delete", principal="ops")
    assert acl.check("order:o1", "delete", principal="ops") is True
    assert acl.check("order:o1", "delete", principal="alice") is False
    assert acl.check("customer:c1", "delete", principal="ops") is False


def test_acl_is_whitelist():
    """无规则 → 拒绝（与 RBAC 无规则开放不同）。"""
    acl = ACLManager()
    assert acl.check("order:o1", "write", principal="alice") is False


def test_permission_mismatch():
    acl = ACLManager()
    acl.grant("order:o1", "read", principal="alice")
    assert acl.check("order:o1", "write", principal="alice") is False


def test_revoke():
    acl = ACLManager()
    acl.grant("order:o1", "write", principal="alice")
    assert acl.check("order:o1", "write", principal="alice") is True
    n = acl.revoke("order:o1", "write", principal="alice")
    assert n == 1
    assert acl.check("order:o1", "write", principal="alice") is False


def test_principal_or_role_either():
    acl = ACLManager()
    acl.grant("order:o1", "write", principal="alice", role="admin")
    assert acl.check("order:o1", "write", principal="alice") is True
    assert acl.check("order:o1", "write", roles=["admin"]) is True
    assert acl.check("order:o1", "write", principal="bob") is False
