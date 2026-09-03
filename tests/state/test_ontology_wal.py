"""Ontology WAL 集成测试。

验证 ObjectStore 写操作（insert/update/delete）通过 wal_hook 桥接到 CheckpointStore。
"""

import pytest

from agentorchestra.ontology.semantic.object_type import ObjectType
from agentorchestra.ontology.storage.backends import MemoryBackend
from agentorchestra.ontology.storage.object_store import ObjectStore
from agentorchestra.tools.base import ToolParameter


def _order_type() -> ObjectType:
    return ObjectType(
        api_name="Order",
        primary_key="id",
        properties=[
            ToolParameter(name="id", type="string", description="id"),
            ToolParameter(name="amount", type="number", description="金额"),
            ToolParameter(name="customer", type="string", description="客户"),
        ],
    )


@pytest.mark.asyncio
async def test_object_store_wal_queue(sqlite_store):
    """插入对象 → _wal_queue 收集条目 → drain 写入 CheckpointStore WAL。"""
    store = ObjectStore(backend=MemoryBackend())
    store.register_type(_order_type())

    # 设置 thread 上下文 + wal hook
    store.set_wal_thread_id("thr-test")
    captured = []

    def hook(tid, action_type, payload):
        captured.append((tid, action_type, payload))

    store.wal_hook = hook

    store.insert("Order", {"id": "o-1", "amount": 100, "customer": "alice"})
    store.insert("Order", {"id": "o-2", "amount": 200, "customer": "bob"})

    # queue 中应该有 2 条
    assert store.pending_wal_count() == 2

    # drain
    entries = store.drain_wal()
    assert len(entries) == 2
    assert all(e["action_type"] == "state_update" for e in entries)
    assert all(e["thread_id"] == "thr-test" for e in entries)

    # drain 后 queue 应清空
    assert store.pending_wal_count() == 0

    # hook 仍然被调用
    assert len(captured) == 2


@pytest.mark.asyncio
async def test_object_store_update_and_delete_emit_wal(sqlite_store):
    store = ObjectStore(backend=MemoryBackend())
    store.register_type(_order_type())
    store.set_wal_thread_id("thr-1")

    store.insert("Order", {"id": "o-1", "amount": 100, "customer": "alice"})
    store.update("Order", "o-1", {"amount": 150})
    store.delete("Order", "o-1")

    entries = store.drain_wal()
    assert len(entries) == 3
    assert entries[0]["payload"]["op"] == "insert"
    assert entries[1]["payload"]["op"] == "update"
    assert entries[1]["payload"]["patch"] == {"amount": 150}
    assert entries[2]["payload"]["op"] == "delete"


@pytest.mark.asyncio
async def test_object_store_no_wal_when_thread_unset(sqlite_store):
    store = ObjectStore(backend=MemoryBackend())
    store.register_type(_order_type())
    # 不设 thread_id
    store.insert("Order", {"id": "o-1", "amount": 100, "customer": "alice"})
    assert store.pending_wal_count() == 0


@pytest.mark.asyncio
async def test_ontology_drain_to_checkpoint_store(sqlite_store):
    """drain 出的 entries 真正写入 CheckpointStore。"""
    store = ObjectStore(backend=MemoryBackend())
    store.register_type(_order_type())
    store.set_wal_thread_id("thr-1")

    await sqlite_store.create_thread("thr-1")
    for i in range(3):
        store.insert("Order", {"id": f"o-{i}", "amount": i * 100, "customer": f"c-{i}"})

    # flush
    from agentorchestra.state.wal import WALEntry
    for entry in store.drain_wal():
        await sqlite_store.append_wal(WALEntry(
            thread_id=entry["thread_id"],
            action_type=entry["action_type"],
            payload=entry["payload"],
        ))

    entries = await sqlite_store.read_wal("thr-1")
    assert len(entries) == 3
