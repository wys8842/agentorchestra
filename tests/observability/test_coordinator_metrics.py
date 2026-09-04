"""coordinator SLO 指标埋点测试。"""

import pytest

from agentorchestra.observability.metrics import (
    enable_prometheus_collector,
    reset_default_collector,
)
from agentorchestra.state.backends.memory_backend import InMemoryCheckpointStore
from agentorchestra.tx import TransactionCoordinator


@pytest.fixture(autouse=True)
def _reset_col():
    reset_default_collector()
    yield
    reset_default_collector()


def _coord(store, collector):
    c = TransactionCoordinator(store=store)
    c.register_action("ok", execute_fn=lambda p, tx: None, compensate_fn=None)
    c.register_action("bad", execute_fn=lambda p, tx: (_ for _ in ()).throw(
        RuntimeError("fail")), compensate_fn=None)
    return c


@pytest.mark.asyncio
async def test_commit_emits_duration():
    pc = enable_prometheus_collector()
    store = InMemoryCheckpointStore()
    await store.init()
    coord = _coord(store, pc)
    async with coord.transaction(idempotency_key="t1") as tx:
        await tx.execute("ok", {})
    text = pc.render()
    assert "tx_duration_seconds_count" in text
    assert 'tx_duration_seconds{result="committed"}' in text or "committed" in text
    # committed 不记 rollback
    assert "tx_rollback_total" not in text


@pytest.mark.asyncio
async def test_abort_emits_rollback():
    pc = enable_prometheus_collector()
    store = InMemoryCheckpointStore()
    await store.init()
    coord = _coord(store, pc)
    with pytest.raises(RuntimeError, match="fail"):
        async with coord.transaction(idempotency_key="t2") as tx:
            await tx.execute("ok", {})
            await tx.execute("bad", {})
    text = pc.render()
    assert "tx_rollback_total" in text
    assert 'tx_duration_seconds' in text


@pytest.mark.asyncio
async def test_noop_zero_impact_without_enable():
    """默认 NoOp：coordinator 跑事务不发任何真实指标。"""
    from agentorchestra.observability.metrics import NoOpCollector

    store = InMemoryCheckpointStore()
    await store.init()
    coord = _coord(store, None)
    async with coord.transaction(idempotency_key="t3") as tx:
        await tx.execute("ok", {})
    # 未 enable → NoOp，render 空
    assert isinstance(__import__("agentorchestra.observability.metrics",
                                 fromlist=["get_default_collector"])
                      .get_default_collector(), NoOpCollector)
