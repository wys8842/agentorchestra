"""Snapshot 测试。"""

import asyncio

import pytest

from agentorchestra.state.checkpoint import Checkpoint
from agentorchestra.state.snapshot import Snapshot, SnapshotPolicy, SnapshotWorker
from agentorchestra.state.thread import ThreadManager
from agentorchestra.state.wal import WALEntry


@pytest.mark.asyncio
async def test_snapshot_triggered_by_count(sqlite_store):
    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread()
    await sqlite_store.save_checkpoint(
        Checkpoint(thread_id=tid, checkpoint_id="cp-1", state={"x": 1})
    )
    # 写入 5 条 WAL（默认阈值 1000）
    for i in range(5):
        await sqlite_store.append_wal(
            WALEntry(thread_id=tid, action_type="checkpoint", payload={"i": i})
        )
    worker = SnapshotWorker(
        store=sqlite_store,
        policy=SnapshotPolicy(wal_threshold=5, interval_seconds=999999, enabled=True),
    )
    snap = await worker.maybe_snapshot(tid)
    assert snap is not None
    assert snap.up_to_seq == 5
    assert snap.state == {"x": 1}


@pytest.mark.asyncio
async def test_snapshot_triggered_by_time(sqlite_store):

    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread()
    await sqlite_store.save_checkpoint(
        Checkpoint(thread_id=tid, checkpoint_id="cp-1", state={"x": 1})
    )
    await sqlite_store.append_wal(
        WALEntry(thread_id=tid, action_type="checkpoint", payload={"x": 1})
    )
    # 先拍一次（count 阈值高 + 时间够新）
    snap1 = Snapshot(
        thread_id=tid, snapshot_id="snap-1", up_to_seq=1, state={"x": 1},
    )
    await sqlite_store.save_snapshot(snap1)
    # 等 0.1s 后设置 interval=0
    await asyncio.sleep(0.1)
    worker = SnapshotWorker(
        store=sqlite_store,
        policy=SnapshotPolicy(wal_threshold=99999, interval_seconds=0, enabled=True),
    )
    snap2 = await worker.maybe_snapshot(tid)
    assert snap2 is not None
    assert snap2.up_to_seq >= 1


@pytest.mark.asyncio
async def test_snapshot_disabled(sqlite_store):
    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread()
    worker = SnapshotWorker(
        store=sqlite_store, policy=SnapshotPolicy(enabled=False)
    )
    assert await worker.maybe_snapshot(tid) is None


@pytest.mark.asyncio
async def test_recovery_from_snapshot_plus_wal(sqlite_store):
    """恢复流程：找最新 snapshot → replay WAL > up_to_seq。"""

    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread()

    # 写 10 个 checkpoint
    for i in range(10):
        await sqlite_store.save_checkpoint(
            Checkpoint(thread_id=tid, checkpoint_id=f"cp-{i}", state={"step": i})
        )
        await sqlite_store.append_wal(
            WALEntry(thread_id=tid, action_type="checkpoint", payload={"step": i})
        )

    # 在第 5 条 WAL 后拍快照
    snap = Snapshot(thread_id=tid, snapshot_id="snap-mid", up_to_seq=5,
                    state={"step": 4})
    await sqlite_store.save_snapshot(snap)

    # 恢复：snapshot up_to_seq=5，replay seq 6-10
    snap_loaded = await sqlite_store.latest_snapshot(tid)
    assert snap_loaded is not None
    assert snap_loaded.up_to_seq == 5
    entries = await sqlite_store.read_wal(tid, after_seq=5, limit=100)
    assert len(entries) == 5
    assert [e.payload["step"] for e in entries] == [5, 6, 7, 8, 9]
