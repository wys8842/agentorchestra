"""coordinator 基础：5-action 成功 commit + WAL 记录。

roadmap §3.6 验收 1：单事务内 5 个 action 全部成功 → commit，WAL 留 5 条。
"""

import pytest

from agentorchestra.state.wal import WALActionType
from agentorchestra.tx import (
    TransactionCoordinator,
    TxReplay,
)


def _make_coord(store):
    c = TransactionCoordinator(store=store)
    calls = []

    def mk(i):
        def execute_fn(p, tx):
            calls.append(f"e{i}")
            return {"i": i, "p": p}

        def compensate_fn(p, tx):
            calls.append(f"c{i}")
        return execute_fn, compensate_fn

    for i in range(5):
        ex, co = mk(i)
        c.register_action(f"action{i}", execute_fn=ex, compensate_fn=co)
    return c, calls


@pytest.mark.asyncio
async def test_five_actions_commit(sqlite_store):
    c, calls = _make_coord(sqlite_store)
    async with c.transaction(idempotency_key="t5") as tx:
        for i in range(5):
            await tx.execute(f"action{i}", {"i": i})
    # 5 次 execute
    assert len(calls) == 5
    assert calls == [f"e{i}" for i in range(5)]
    # 幂等 completed
    rec = await sqlite_store.get_idempotency("t5")
    assert rec is not None
    assert rec.status == "completed"


@pytest.mark.asyncio
async def test_wal_has_begin_and_actions(sqlite_store):
    """WAL：TX_BEGIN + 5 条 STATE_UPDATE + TX_COMMIT。"""
    c, _ = _make_coord(sqlite_store)
    async with c.transaction(idempotency_key="wal5") as tx:
        for i in range(5):
            await tx.execute(f"action{i}", {"i": i})

    entries = await sqlite_store.read_wal("default")
    action_entries = [e for e in entries if e.action_type == WALActionType.STATE_UPDATE]
    begin = [e for e in entries if e.action_type == WALActionType.TX_BEGIN]
    commit = [e for e in entries if e.action_type == WALActionType.TX_COMMIT]
    assert len(action_entries) == 5
    assert len(begin) == 1
    assert len(commit) == 1
    # tx_id 关联
    tx_ids = {e.tx_id for e in entries if e.tx_id}
    assert len(tx_ids) == 1


@pytest.mark.asyncio
async def test_commit_uses_memory_store_no_db():
    """不传 store → in-memory，不落 DB 也能跑通。"""
    c, calls = _make_coord(None)
    async with c.transaction() as tx:
        await tx.execute("action0", {"i": 0})
    assert calls == ["e0"]
    assert len(c.list_actions()) == 5


@pytest.mark.asyncio
async def test_idempotency_replay_returns_result(sqlite_store):
    """同 key 二次提交 → TxReplay（首次结果）。"""
    c, _ = _make_coord(sqlite_store)
    async with c.transaction(idempotency_key="replay1") as tx:
        await tx.execute("action0", {"i": 0})
        await tx.execute("action1", {"i": 1})

    with pytest.raises(TxReplay) as ei:
        async with c.transaction(idempotency_key="replay1") as tx:
            await tx.execute("action0", {"i": 0})
    assert ei.value.result  # 首次结果被重放
