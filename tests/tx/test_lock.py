"""乐观锁 / CAS 冲突测试。

roadmap §3.2 锁模型：乐观锁（version 比对）+ 冲突升级抛 TxConflict。
"""

import asyncio

import pytest

from agentorchestra.tx import TransactionCoordinator, TxConflict


@pytest.mark.asyncio
async def test_acquire_lock_and_cas(sqlite_store):
    """锁获取 + CAS 版本递增。"""
    rec = await sqlite_store.acquire_lock("order:1", "tx-1", ttl_seconds=30)
    assert rec is not None
    assert rec.version == 0

    # CAS 成功：0→1
    assert await sqlite_store.compare_and_swap("order:1", 0, "tx-1") is True
    # CAS 重复（版本已 1）：失败
    assert await sqlite_store.compare_and_swap("order:1", 0, "tx-1") is False
    assert await sqlite_store.read_version("order:1") == 1


@pytest.mark.asyncio
async def test_lock_conflict_returns_none(sqlite_store):
    """已持有锁（未过期）→ 第二次 acquire 返回 None。"""
    r1 = await sqlite_store.acquire_lock("order:1", "tx-1", ttl_seconds=30)
    assert r1 is not None
    r2 = await sqlite_store.acquire_lock("order:1", "tx-2", ttl_seconds=30)
    assert r2 is None


@pytest.mark.asyncio
async def test_release_only_owner(sqlite_store):
    """仅 owner 能释放。"""
    await sqlite_store.acquire_lock("order:1", "tx-1", ttl_seconds=30)
    assert await sqlite_store.release_lock("order:1", "tx-2") is False
    assert await sqlite_store.release_lock("order:1", "tx-1") is True
    assert await sqlite_store.read_version("order:1") is None


@pytest.mark.asyncio
async def test_pre_condition_conflict(sqlite_store):
    """两个并发事务抢同一资源：先到 pre_condition 成功，后者失败。"""
    c1 = TransactionCoordinator(store=sqlite_store)
    c2 = TransactionCoordinator(store=sqlite_store)

    async def tx1():
        async with c1.transaction(resources=["order:1"]) as tx:
            assert await tx.pre_condition("order:1") is True
            await asyncio.sleep(0.2)  # 持锁期间

    async def tx2():
        await asyncio.sleep(0.05)
        with pytest.raises(TxConflict):
            async with c2.transaction(resources=["order:1"]) as tx:
                await tx.execute("dummy", {})

    c1.register_action("dummy", execute_fn=lambda p, tx: None, compensate_fn=None)
    c2.register_action("dummy", execute_fn=lambda p, tx: None, compensate_fn=None)

    await asyncio.gather(tx1(), tx2())


@pytest.mark.asyncio
async def test_expected_version_cas(sqlite_store):
    """pre_condition(expected_version) 版本不匹配 → False（不抛）。"""
    c = TransactionCoordinator(store=sqlite_store)
    # 无锁记录 → version None → 返回 False
    async with c.transaction() as tx:
        assert await tx.pre_condition("order:x", expected_version=0) is False
