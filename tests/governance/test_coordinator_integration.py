"""coordinator + governance 集成测试。

roadmap §5.5 验收：无权修改 → pre-condition 抛 PermissionDenied；并发 CAS。
"""


import pytest

from agentorchestra.governance import (
    ACLManager,
    PermissionChecker,
    PermissionDenied,
)
from agentorchestra.tx import TransactionCoordinator


def _order_security():
    from agentorchestra.ontology.governance.security import SecurityManager

    sec = SecurityManager()
    sec.allow(["admin"], resource="*", action="*")
    sec.allow(["viewer"], resource="Order", action="read")
    return sec


def _viewer_can_write_order():
    """RBAC：viewer 类型级可写 Order，行级由 ACL 约束。"""
    from agentorchestra.ontology.governance.security import SecurityManager

    sec = SecurityManager()
    sec.allow(["viewer"], resource="Order", action="*")
    return sec


@pytest.mark.asyncio
async def test_principal_injected_into_ctx(memory_store):
    coord = TransactionCoordinator(store=memory_store)
    coord.register_action("a", execute_fn=lambda p, tx: tx.principal)
    async with coord.transaction(principal="alice", roles=["admin"]) as tx:
        r = await tx.execute("a", {})
        assert tx.principal == "alice"
        assert tx.roles == ["admin"]
    assert r == "alice"


@pytest.mark.asyncio
async def test_identity_context_available_in_action(memory_store):
    """动作内部经 IdentityService 读到当前 principal。"""
    from agentorchestra.governance.identity import current_principal

    seen = {}
    coord = TransactionCoordinator(store=memory_store)
    coord.register_action("who", execute_fn=lambda p, tx: seen.__setitem__(
        "who", current_principal()))
    async with coord.transaction(principal="bob") as tx:
        await tx.execute("who", {})
    assert seen["who"] == "bob"


@pytest.mark.asyncio
async def test_permission_denied_aborts_transaction(memory_store):
    """authorize 失败抛 PermissionDenied；事务状态 aborted（补偿已成功动作）。"""
    sec = _order_security()
    pc = PermissionChecker(security=sec)
    coord = TransactionCoordinator(store=memory_store, permission_checker=pc)
    calls = []

    def exec_a(p, tx):
        calls.append("a")

    def comp_a(p, tx):
        calls.append("comp_a")

    coord.register_action("a", execute_fn=exec_a, compensate_fn=comp_a)

    with pytest.raises(PermissionDenied):
        async with coord.transaction(
            principal="viewer", roles=["viewer"],
        ) as tx:
            await tx.execute("a", {})  # RBAC: viewer 可 read 不可 write Order
            tx.authorize("Order", "write")  # → PermissionDenied

    # viewer 无 Order.write → PermissionDenied 触发；a 已执行后被补偿
    assert "a" in calls
    assert "comp_a" in calls


@pytest.mark.asyncio
async def test_authorize_allowed_for_admin(memory_store):
    sec = _order_security()
    pc = PermissionChecker(security=sec)
    coord = TransactionCoordinator(store=memory_store, permission_checker=pc)
    async with coord.transaction(principal="root", roles=["admin"]) as tx:
        tx.authorize("Order", "write")
        # 不抛异常 → 通过


@pytest.mark.asyncio
async def test_row_level_acl_in_authorize(memory_store):
    sec = _viewer_can_write_order()
    acl = ACLManager()
    acl.grant("Order:o1", "write", principal="alice")
    pc = PermissionChecker(security=sec, acl=acl)
    coord = TransactionCoordinator(store=memory_store, permission_checker=pc)

    # viewer（RBAC 可写 Order）但没有 o1 行 ACL → 拒绝
    with pytest.raises(PermissionDenied):
        async with coord.transaction(principal="bob", roles=["viewer"]) as tx:
            tx.authorize("Order", "write", obj_id="o1")

    # alice 有 o1 ACL → 放行
    async with coord.transaction(principal="alice", roles=["viewer"]) as tx:
        tx.authorize("Order", "write", obj_id="o1")


@pytest.mark.asyncio
async def test_identity_reset_after_transaction(memory_store):
    """事务退出后 ContextVar 还原。"""
    from agentorchestra.governance.identity import current_principal

    coord = TransactionCoordinator(store=memory_store)
    async with coord.transaction(principal="carol"):
        assert current_principal() == "carol"
    assert current_principal() == "anonymous"
