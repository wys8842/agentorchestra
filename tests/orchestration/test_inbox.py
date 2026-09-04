"""Inbox 测试：消息持久化 / TTL 过期清理 / ack 回执。"""

from datetime import datetime, timedelta

import pytest

from agentorchestra.orchestration import Inbox


@pytest.mark.asyncio
async def test_send_and_poll(memory_store):
    inbox = Inbox(memory_store, default_ttl_seconds=604800)
    mid = await inbox.send("g1", "t1", "coder", {"task": "x"})
    msgs = await inbox.poll("t1", to_node="coder")
    assert len(msgs) == 1
    assert msgs[0].msg_id == mid
    assert msgs[0].content == {"task": "x"}
    assert msgs[0].status == "queued"


@pytest.mark.asyncio
async def test_delivered_not_in_pending(memory_store):
    inbox = Inbox(memory_store)
    mid = await inbox.send("g1", "t1", "coder", {"task": "x"})
    token = await inbox.mark_delivered(mid)
    assert token.startswith("ack-")
    assert await inbox.poll("t1") == []


@pytest.mark.asyncio
async def test_ack_writes_receipt(memory_store):
    inbox = Inbox(memory_store)
    mid = await inbox.send("g1", "t1", "coder", {"task": "x"})
    await inbox.ack(mid, "ack-1", "acked")
    # ack 后消息状态 = acked，不再 pending
    assert await inbox.poll("t1") == []


@pytest.mark.asyncio
async def test_ttl_expired_cleaned_up(memory_store):

    # 用短 TTL 模拟 7 天（同语义）
    inbox = Inbox(memory_store, default_ttl_seconds=1)
    mid = await inbox.send("g1", "t1", "coder", {"task": "x"}, ttl_seconds=1)
    await inbox.send("g1", "t1", "coder", {"task": "y"}, ttl_seconds=3600)
    # 快进过期
    msg = await memory_store.list_pending_messages("t1")
    for m in msg:
        if m.msg_id == mid:
            m.expires_at = datetime.now() - timedelta(seconds=1)
            await memory_store.enqueue_message(m)
    n = await inbox.cleanup()
    assert n >= 1
    pending = await inbox.poll("t1")
    assert all(m.msg_id != mid for m in pending)


@pytest.mark.asyncio
async def test_delete_expired_messages_interface(memory_store):
    from agentorchestra.state.records import InboxMessage

    expired = InboxMessage(
        msg_id="old1", graph_id="g", thread_id="t", to_node="n", content={},
        expires_at=datetime.now() - timedelta(seconds=5),
    )
    await memory_store.enqueue_message(expired)
    n = await memory_store.delete_expired_messages()
    assert n >= 1
