"""DLQ 测试。

roadmap §3.6 验收 3：compensate 连续失败 3 次 → 进 DLQ，事务标记 compensation_failed。
"""

import pytest

from agentorchestra.tx import TransactionCoordinator


@pytest.mark.asyncio
async def test_compensation_failure_goes_to_dlq(sqlite_store):
    c = TransactionCoordinator(store=sqlite_store, compensation_retries=3)
    calls = {"execute": 0, "compensate": 0}

    def failing_compensate(p, tx):
        calls["compensate"] += 1
        raise RuntimeError("无法补偿")

    c.register_action("good", execute_fn=lambda p, tx: None,
                      compensate_fn=failing_compensate)
    c.register_action("bad", execute_fn=lambda p, tx: (_ for _ in ()).throw(
        RuntimeError("bad 失败")),
        compensate_fn=None)

    with pytest.raises(RuntimeError, match="bad 失败"):
        async with c.transaction(idempotency_key="dlq1") as tx:
            await tx.execute("good", {})
            await tx.execute("bad", {})

    # 补偿重试 3 次后进 DLQ
    assert calls["compensate"] == 3
    dlq = await sqlite_store.list_dlq(status="open")
    assert len(dlq) == 1
    assert dlq[0].action_name == "good"
    assert dlq[0].attempts == 3


@pytest.mark.asyncio
async def test_compensation_success_not_in_dlq(sqlite_store):
    c = TransactionCoordinator(store=sqlite_store, compensation_retries=3)
    c.register_action("good", execute_fn=lambda p, tx: None,
                      compensate_fn=lambda p, tx: None)
    c.register_action("bad", execute_fn=lambda p, tx: (_ for _ in ()).throw(
        RuntimeError("bad")), compensate_fn=None)

    with pytest.raises(RuntimeError):
        async with c.transaction() as tx:
            await tx.execute("good", {})
            await tx.execute("bad", {})

    dlq = await sqlite_store.list_dlq(status="open")
    assert len(dlq) == 0
