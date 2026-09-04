"""补偿测试。

roadmap §3.6 验收 2：第 3 个 action 抛异常 → 自动 compensate 1、2，进入成功态（aborted）。
"""

import pytest

from agentorchestra.tx import TransactionCoordinator


def _make_failing_coord(store):
    """action0/action1 成功；action2 抛异常。"""
    c = TransactionCoordinator(store=store)
    calls = []
    state = {"x": 0}

    def on_action2(p, tx):
        raise RuntimeError("action2 失败")

    c.register_action("action0", execute_fn=lambda p, tx: state.__setitem__("x", 1),
                      compensate_fn=lambda p, tx: state.__setitem__("x", 0))
    c.register_action("action1", execute_fn=lambda p, tx: state.__setitem__("x", 2),
                      compensate_fn=lambda p, tx: state.__setitem__("x", 1))
    c.register_action("action2", execute_fn=on_action2, compensate_fn=lambda p, tx: None)
    return c, calls, state


@pytest.mark.asyncio
async def test_third_action_failure_triggers_reverse_compensation(sqlite_store):
    c, calls, state = _make_failing_coord(sqlite_store)
    with pytest.raises(RuntimeError, match="action2 失败"):
        async with c.transaction() as tx:
            await tx.execute("action0", {})
            await tx.execute("action1", {})
            await tx.execute("action2", {})

    # 补偿逆序：action1 → action0（在 coordinator 内部完成）
    # state 应回到初始 0（action0 补偿把 2→1→... 我们验证最终一致性）
    # action0 补偿：x 设 0；action1 补偿：x 设 1 → 最终 action0 先补（1→? ）
    # 逆序: action1 补偿 (x=2→1), 然后 action0 补偿 (x=1→0)
    assert state["x"] == 0


@pytest.mark.asyncio
async def test_abort_raises_to_caller(sqlite_store):
    """TxAbort（pre-condition 失败）触发补偿且状态 aborted。"""
    from agentorchestra.tx import TxAbort

    c, _, state = _make_failing_coord(sqlite_store)
    # 只成功 action0 后主动 abort
    with pytest.raises(TxAbort):
        async with c.transaction() as tx:
            await tx.execute("action0", {})
            raise TxAbort("pre-condition failed")
    assert state["x"] == 0  # action0 已补偿
