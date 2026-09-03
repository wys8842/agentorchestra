"""WAL 测试。"""

import pytest

from agentorchestra.state.wal import WALActionType, WALEntry


@pytest.mark.asyncio
async def test_wal_append_returns_sequence(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    e1 = WALEntry(thread_id="thr-1", action_type="checkpoint", payload={"x": 1})
    e2 = WALEntry(thread_id="thr-1", action_type="state_update", payload={"x": 2})
    s1 = await sqlite_store.append_wal(e1)
    s2 = await sqlite_store.append_wal(e2)
    assert s1 == 1
    assert s2 == 2
    assert e1.sequence_no == 1
    assert e2.sequence_no == 2


@pytest.mark.asyncio
async def test_wal_per_thread_sequence_independent(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    await sqlite_store.create_thread("thr-2")
    s1 = await sqlite_store.append_wal(
        WALEntry(thread_id="thr-1", action_type="checkpoint", payload={})
    )
    s2 = await sqlite_store.append_wal(
        WALEntry(thread_id="thr-2", action_type="checkpoint", payload={})
    )
    s3 = await sqlite_store.append_wal(
        WALEntry(thread_id="thr-1", action_type="checkpoint", payload={})
    )
    # 不同 thread 的 sequence_no 独立从 1 开始
    assert s1 == 1
    assert s2 == 1
    assert s3 == 2


@pytest.mark.asyncio
async def test_wal_read_after_seq(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    for i in range(5):
        await sqlite_store.append_wal(
            WALEntry(thread_id="thr-1", action_type="checkpoint", payload={"i": i})
        )
    entries = await sqlite_store.read_wal("thr-1", after_seq=2, limit=10)
    assert len(entries) == 3
    assert [e.payload["i"] for e in entries] == [2, 3, 4]


@pytest.mark.asyncio
async def test_max_wal_seq(sqlite_store):
    await sqlite_store.create_thread("thr-1")
    assert await sqlite_store.max_wal_seq("thr-1") == 0
    for i in range(3):
        await sqlite_store.append_wal(
            WALEntry(thread_id="thr-1", action_type="checkpoint", payload={"i": i})
        )
    assert await sqlite_store.max_wal_seq("thr-1") == 3


@pytest.mark.asyncio
async def test_wal_entry_serialization():
    e = WALEntry(thread_id="t", action_type=WALActionType.INTERRUPT, payload={"k": "v"})
    d = e.to_dict()
    e2 = WALEntry.from_dict(d)
    assert e2.thread_id == e.thread_id
    assert e2.action_type == e.action_type
    assert e2.payload == e.payload
