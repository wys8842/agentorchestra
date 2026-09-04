"""Idempotency 测试。

roadmap §3.6 验收 4：同 idempotency_key 二次提交 → 直接返回首次结果。
"""

import pytest

from agentorchestra.state.records import IdempotencyRecord
from agentorchestra.tx import IdempotencyStore, TransactionCoordinator, TxReplay


@pytest.mark.asyncio
async def test_generate_key_deterministic():
    a = IdempotencyStore.generate_key("tx", ["a", "b"])
    b = IdempotencyStore.generate_key("tx", ["a", "b"])
    c = IdempotencyStore.generate_key("tx", ["a", "c"])
    assert a == b
    assert a != c


@pytest.mark.asyncio
async def test_begin_complete_lifecycle(sqlite_store):
    st = IdempotencyStore(sqlite_store, ttl_seconds=3600)
    ok = await st.begin("k1", "h1", "tx-1")
    assert ok is True
    rec = await st.get("k1")
    assert rec.status == "running"

    await st.complete("k1", {"ok": 1}, "tx-1")
    rec = await st.get("k1")
    assert rec.status == "completed"
    assert rec.result == {"ok": 1}


@pytest.mark.asyncio
async def test_begin_returns_false_when_completed(sqlite_store):
    st = IdempotencyStore(sqlite_store)
    await st.begin("k1", "h1", "tx-1")
    await st.complete("k1", {"ok": 1}, "tx-1")
    ok = await st.begin("k1", "h1", "tx-2")
    assert ok is False


@pytest.mark.asyncio
async def test_ttl_expired_returns_none(sqlite_store):
    """TTL 过期后 get 返回 None（可重放）。"""
    from datetime import datetime, timedelta

    rec = IdempotencyRecord(
        idempotency_key="expired1",
        request_hash="h",
        status="completed",
        result={"ok": 1},
        expires_at=datetime.now() - timedelta(seconds=1),
    )
    await sqlite_store.put_idempotency(rec)
    got = await sqlite_store.get_idempotency("expired1")
    assert got is None
    # cleanup 能删掉
    n = await sqlite_store.delete_expired_idempotency()
    assert n >= 1


@pytest.mark.asyncio
async def test_coordinator_auto_key_generated(sqlite_store):
    """未显式传 key → 自动生成（基于动作签名）。

    相同动作集的两次事务命中同一自动 key → 第二次触发幂等重放 TxReplay。
    不同动作集 → 不同 key，不冲突。
    """
    c = TransactionCoordinator(store=sqlite_store)
    c.register_action("a", execute_fn=lambda p, tx: None, compensate_fn=None)
    async with c.transaction() as tx:
        await tx.execute("a", {})

    # 同动作集第二次 → 幂等重放
    with pytest.raises(TxReplay):
        async with c.transaction() as tx:
            await tx.execute("a", {})

    # 不同动作集 → key 不同，不冲突
    c2 = TransactionCoordinator(store=sqlite_store)
    c2.register_action("b", execute_fn=lambda p, tx: None, compensate_fn=None)
    async with c2.transaction() as tx:
        await tx.execute("b", {})
