"""WORM 审计测试：append-only；无 update/delete 方法；query 过滤。"""

import pytest

from agentorchestra.state.records import AuditEntry


def test_no_update_or_delete_methods():
    """接口层不暴露 update_audit/delete_audit/clear_audit（WORM）。"""
    from agentorchestra.state.checkpoint import CheckpointStore

    forbidden = {"update_audit", "delete_audit", "clear_audit"}
    for name in forbidden:
        assert not hasattr(CheckpointStore, name)


@pytest.mark.asyncio
async def test_append_and_query(memory_store):
    await memory_store.append_audit(AuditEntry(
        principal="alice", resource="Order", action="write", obj_id="o1",
        success=True, detail={"v": 1}))
    await memory_store.append_audit(AuditEntry(
        principal="bob", resource="Order", action="delete", success=False))
    await memory_store.append_audit(AuditEntry(
        principal="alice", resource="Customer", action="write", obj_id="c1"))

    all_ = await memory_store.query_audit()
    assert len(all_) == 3
    assert all_[0].principal == "alice"  # 倒序

    alice = await memory_store.query_audit(principal="alice")
    assert len(alice) == 2

    order_writes = await memory_store.query_audit(resource="Order")
    assert len(order_writes) == 2


@pytest.mark.asyncio
async def test_sqlite_worm(sqlite_store):
    await sqlite_store.append_audit(AuditEntry(
        principal="alice", resource="Order", action="write", success=True))
    entries = await sqlite_store.query_audit()
    assert len(entries) == 1
    assert entries[0].principal == "alice"
    assert entries[0].success is True


@pytest.mark.asyncio
async def test_audit_through_object_store(sqlite_store):
    """ObjectStore 写操作装配审计后自动记录（WORM append-only）。"""
    import asyncio

    from agentorchestra.governance import IdentityService
    from agentorchestra.ontology.governance.audit import AuditManager

    # 用带 store backend 的 AuditManager
    audit_mgr = AuditManager()
    audit_mgr.attach_backend(sqlite_store)

    from agentorchestra.ontology.semantic.object_type import ObjectType
    from agentorchestra.ontology.storage.object_store import ObjectStore
    from agentorchestra.tools.base import ToolParameter

    ot = ObjectType(api_name="Order", primary_key="id", properties=[
        ToolParameter(name="id", type="string", description=""),
        ToolParameter(name="amount", type="number", description=""),
    ])
    s = ObjectStore()
    s.register_type(ot)
    s.configure_governance(audit=audit_mgr)
    svc = IdentityService()
    with svc.sync_run_as("alice", ["admin"]):
        s.insert("Order", {"id": "o1", "amount": 100})
    # 给 fire-and-forget task 时间
    await asyncio.sleep(0.05)
    # 审计记录落 WORM 后端（alice 操作 Order）
    entries = await sqlite_store.query_audit(principal="alice", resource="Order")
    assert len(entries) == 1
    assert entries[0].action == "insert"
