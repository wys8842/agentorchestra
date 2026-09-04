"""identity 测试：ContextVar principal/roles 上下文。"""

import asyncio

from agentorchestra.governance.identity import IdentityService, current_principal


def test_default_principal():
    svc = IdentityService()
    assert svc.principal == "anonymous"
    assert current_principal() == "anonymous"


def test_sync_run_as_restores():
    svc = IdentityService()
    with svc.sync_run_as("alice", ["admin"]):
        assert svc.principal == "alice"
        assert svc.roles == ["admin"]
    assert svc.principal == "anonymous"  # 退出还原


async def test_async_run_as():
    svc = IdentityService()
    async with svc.run_as("bob", ["viewer"]):
        assert svc.principal == "bob"
        assert current_principal() == "bob"
    assert current_principal() == "anonymous"


async def test_run_as_isolated_between_tasks():
    """两个并发任务持有不同身份。"""
    svc = IdentityService()

    async def task1():
        async with svc.run_as("alice", ["admin"]):
            await asyncio.sleep(0.05)
            return svc.principal

    async def task2():
        async with svc.run_as("carol", ["finance"]):
            await asyncio.sleep(0.01)
            return svc.principal

    r1, r2 = await asyncio.gather(task1(), task2())
    assert (r1, r2) == ("alice", "carol")
