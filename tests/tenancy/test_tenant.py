"""TenantContext 测试。"""

from agentorchestra.tenancy import TenantManager


def test_namespace_default():
    assert TenantManager.namespace() == "default"
    assert TenantManager.tenant_id() is None


def test_sync_run_as_sets_context():
    tm = TenantManager()
    with tm.sync_run_as("acme", "alice"):
        assert tm.tenant_id() == "acme"
        assert tm.namespace() == "acme:alice"
        assert tm.current().user_id == "alice"
    # 退出还原
    assert tm.tenant_id() is None


def test_sync_run_as_no_user():
    tm = TenantManager()
    with tm.sync_run_as("acme"):
        assert tm.namespace() == "acme"


def test_nested_context_restores():
    tm = TenantManager()
    with tm.sync_run_as("a", "u1"):
        assert tm.namespace() == "a:u1"
        with tm.sync_run_as("b", "u2"):
            assert tm.namespace() == "b:u2"
        assert tm.namespace() == "a:u1"


async def test_async_run_as():
    import asyncio

    tm = TenantManager()

    async def job(name):
        async with tm.run_as(name, "u"):
            await asyncio.sleep(0.01)
            return tm.tenant_id()

    r1, r2 = await asyncio.gather(job("x"), job("y"))
    assert (r1, r2) == ("x", "y")
