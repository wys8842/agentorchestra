"""Interrupt 协议测试。"""

import pytest

from agentorchestra.state.interrupt import Interrupt, InterruptStatus


@pytest.mark.asyncio
async def test_create_and_resolve_interrupt(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    intr = Interrupt(
        token="int-abc",
        thread_id="thr-1",
        checkpoint_id="cp-1",
        reason="需要审批",
        payload={"amount": 1000},
    )
    await sqlite_store.create_interrupt(intr)
    loaded = await sqlite_store.get_interrupt("int-abc")
    assert loaded is not None
    assert loaded.reason == "需要审批"
    assert loaded.payload == {"amount": 1000}
    assert loaded.status == InterruptStatus.PENDING

    await sqlite_store.resolve_interrupt("int-abc", {"approved": True})
    loaded = await sqlite_store.get_interrupt("int-abc")
    assert loaded.status == InterruptStatus.RESUMED
    assert loaded.response == {"approved": True}
    assert loaded.resolved_at is not None


@pytest.mark.asyncio
async def test_get_nonexistent_interrupt(sqlite_store):
    assert await sqlite_store.get_interrupt("nope") is None


@pytest.mark.asyncio
async def test_interrupt_pending_exception():
    from agentorchestra.state.interrupt import InterruptPending

    e = InterruptPending(token="t-1", reason="审批", payload={"x": 1})
    assert e.token == "t-1"
    assert e.reason == "审批"
    assert e.payload == {"x": 1}
    assert "t-1" in str(e)
