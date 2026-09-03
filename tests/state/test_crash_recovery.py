"""Crash recovery 模拟测试。

模拟 Agent 中途 kill（不继续写）→ 新 store 实例化 → resume → 验证 state 完整。
"""

import pytest

from agentorchestra.state.backends.sqlite_backend import SQLiteCheckpointStore
from agentorchestra.state.checkpoint import Checkpoint
from agentorchestra.state.thread import ThreadManager
from agentorchestra.state.wal import WALEntry


@pytest.mark.asyncio
async def test_crash_recovery_resume_after_kill(sqlite_store):
    """模拟：Agent 跑了 5 步后被 kill，从 sqlite 重新构造 → 从第 5 步恢复。"""
    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread(metadata={"user": "alice"})

    # 跑 5 步（每步保存 checkpoint + WAL）
    history = []
    for i in range(5):
        history.append(f"step-{i}")
        cp = Checkpoint(
            thread_id=tid,
            checkpoint_id=f"cp-{i}",
            state={"history": list(history), "step": i},
        )
        await sqlite_store.save_checkpoint(cp)
        await sqlite_store.append_wal(
            WALEntry(thread_id=tid, action_type="checkpoint", payload={"step": i})
        )

    # ===== 模拟 kill：丢弃旧 store，重新打开 =====
    db_path = sqlite_store._db_url.replace("sqlite+aiosqlite:///", "")
    await sqlite_store.close()

    # 新 store 实例（"重启进程"）
    new_store = SQLiteCheckpointStore(f"sqlite+aiosqlite:///{db_path}")
    await new_store.init()
    new_mgr = ThreadManager(new_store)

    try:
        # resume：取最新 checkpoint
        cp = await new_mgr.latest_checkpoint(tid)
        assert cp is not None
        assert cp.state["step"] == 4
        assert len(cp.state["history"]) == 5

        # 验证 thread 还在
        thread = await new_mgr.get(tid)
        assert thread is not None
        assert thread.metadata == {"user": "alice"}

        # 验证 WAL 完整（5 条）
        entries = await new_store.read_wal(tid)
        assert len(entries) == 5
    finally:
        await new_store.close()


@pytest.mark.asyncio
async def test_crash_recovery_with_snapshot(sqlite_store):
    """带 snapshot 的崩溃恢复：snapshot 压缩后 replay 应只从 up_to_seq 后开始。"""
    from agentorchestra.state.snapshot import Snapshot

    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread()

    # 写 20 个 checkpoint
    for i in range(20):
        await sqlite_store.save_checkpoint(
            Checkpoint(thread_id=tid, checkpoint_id=f"cp-{i}",
                       state={"history": list(range(i + 1)), "step": i})
        )
        await sqlite_store.append_wal(
            WALEntry(thread_id=tid, action_type="checkpoint", payload={"i": i})
        )

    # 在 seq=10 后拍快照
    snap = Snapshot(thread_id=tid, snapshot_id="snap-mid", up_to_seq=10,
                    state={"history": list(range(10)), "step": 9})
    await sqlite_store.save_snapshot(snap)

    # 模拟 kill + 重启
    db_path = sqlite_store._db_url.replace("sqlite+aiosqlite:///", "")
    await sqlite_store.close()
    new_store = SQLiteCheckpointStore(f"sqlite+aiosqlite:///{db_path}")
    await new_store.init()

    try:
        # 恢复算法：snapshot + replay WAL > up_to_seq
        snap_loaded = await new_store.latest_snapshot(tid)
        assert snap_loaded.up_to_seq == 10
        latest_cp = await new_store.latest_checkpoint(tid)
        assert latest_cp.state["step"] == 19

        # replay 只需 10-19 共 10 条
        entries = await new_store.read_wal(tid, after_seq=10, limit=100)
        assert len(entries) == 10
    finally:
        await new_store.close()


@pytest.mark.asyncio
async def test_crash_recovery_ontology_state(sqlite_store):
    """Ontology 对象变更走 WAL，重启后能查回。"""
    mgr = ThreadManager(sqlite_store)
    tid = await mgr.create_thread()

    # 模拟 5 个 ontology state_update
    for i in range(5):
        await sqlite_store.append_wal(WALEntry(
            thread_id=tid,
            action_type="state_update",
            payload={"op": "insert", "type": "Order", "pk": f"o-{i}",
                     "obj": {"id": f"o-{i}", "amount": i * 100}},
        ))

    # kill + restart
    db_path = sqlite_store._db_url.replace("sqlite+aiosqlite:///", "")
    await sqlite_store.close()
    new_store = SQLiteCheckpointStore(f"sqlite+aiosqlite:///{db_path}")
    await new_store.init()

    try:
        entries = await new_store.read_wal(tid)
        assert len(entries) == 5
        assert all(e.action_type.value == "state_update" for e in entries)
        orders = [e.payload["obj"] for e in entries]
        assert orders[2]["amount"] == 200
    finally:
        await new_store.close()
