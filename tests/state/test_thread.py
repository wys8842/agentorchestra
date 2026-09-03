"""Thread 管理器测试。"""

import pytest

from agentorchestra.state.thread import ThreadManager, ThreadStatus


@pytest.mark.asyncio
async def test_create_thread_generates_id(sqlite_store):
    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread(metadata={"user": "alice"})
    assert tid.startswith("thr-")
    t = await mgr.get(tid)
    assert t is not None
    assert t.metadata == {"user": "alice"}
    assert t.status == ThreadStatus.ACTIVE


@pytest.mark.asyncio
async def test_create_thread_with_custom_id(sqlite_store):
    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread(thread_id="custom-id", metadata={"k": "v"})
    assert tid == "custom-id"
    t = await mgr.get("custom-id")
    assert t is not None


@pytest.mark.asyncio
async def test_update_thread_status(sqlite_store):
    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread()
    await mgr.update_status(tid, ThreadStatus.COMPLETED)
    t = await mgr.get(tid)
    assert t.status == ThreadStatus.COMPLETED


@pytest.mark.asyncio
async def test_save_checkpoint_via_thread_manager(sqlite_store):
    from agentorchestra.state.checkpoint import Checkpoint

    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread()
    cp = Checkpoint(thread_id=tid, checkpoint_id="cp-1", state={"x": 1})
    await mgr.save_checkpoint(cp)
    cps = await mgr.list_checkpoints(tid)
    assert len(cps) == 1
    # WAL 也应该同步写入
    seqs = await sqlite_store.read_wal(tid)
    assert any(e.action_type.value == "checkpoint" for e in seqs)


@pytest.mark.asyncio
async def test_get_nonexistent_thread(sqlite_store):
    mgr = ThreadManager(sqlite_store)
    assert await mgr.get("nonexistent") is None
