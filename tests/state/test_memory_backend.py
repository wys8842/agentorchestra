"""InMemory backend 测试（也间接测试基类抽象）。"""

import pytest

from agentorchestra.state.backends.memory_backend import InMemoryCheckpointStore
from agentorchestra.state.checkpoint import Checkpoint
from agentorchestra.state.interrupt import Interrupt
from agentorchestra.state.wal import WALEntry


@pytest.mark.asyncio
async def test_memory_store_basic_lifecycle():
    store = InMemoryCheckpointStore()
    await store.init()
    try:
        await store.create_thread("t1")
        await store.save_checkpoint(Checkpoint(
            thread_id="t1", checkpoint_id="cp-1", state={"x": 1}
        ))
        await store.append_wal(WALEntry(
            thread_id="t1", action_type="checkpoint", payload={}
        ))
        cp = await store.latest_checkpoint("t1")
        assert cp.state == {"x": 1}
        assert await store.max_wal_seq("t1") == 1
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_memory_store_interrupt():
    store = InMemoryCheckpointStore()
    await store.init()
    try:
        await store.create_thread("t1")
        intr = Interrupt(token="int-1", thread_id="t1", checkpoint_id="cp-1",
                         reason="审批")
        await store.create_interrupt(intr)
        loaded = await store.get_interrupt("int-1")
        assert loaded.reason == "审批"
        await store.resolve_interrupt("int-1", {"ok": True})
        loaded = await store.get_interrupt("int-1")
        assert loaded.status.value == "resumed"
        assert loaded.response == {"ok": True}
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_get_default_store_in_memory():
    """验证 get_default_store('in_memory://') 不引入 DB 依赖。"""
    from agentorchestra.state import get_default_store
    store = get_default_store("in_memory://")
    assert isinstance(store, InMemoryCheckpointStore)
