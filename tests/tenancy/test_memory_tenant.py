"""Memory + tenant 隔离测试（roadmap §8.5 验收 1：两租户完全隔离）。"""

from agentorchestra.memory.models import MemoryType
from agentorchestra.tenancy import TenantManager


def test_tenant_namespace_isolation(memory_manager):
    tm = TenantManager()
    with tm.sync_run_as("tenant_a", "u1"):
        memory_manager.remember("A 的私有记忆", type=MemoryType.FACT)
        hits_a = memory_manager.recall("私有", namespace=None)
    with tm.sync_run_as("tenant_b", "u2"):
        memory_manager.remember("B 的私有记忆", type=MemoryType.FACT)
        hits_b = memory_manager.recall("私有", namespace=None)

    # 各租户只能看到自己的
    assert len(hits_a) == 1 and "A 的" in hits_a[0].content
    assert len(hits_b) == 1 and "B 的" in hits_b[0].content
    # 互不可见（即使 recall 返回条目，namespace 也必须属于当前租户）
    with tm.sync_run_as("tenant_a", "u1"):
        hits = memory_manager.recall("B 的", namespace=None)
        assert all(h.namespace.startswith("tenant_a") for h in hits)
        assert all("B 的" not in h.content for h in hits)
    with tm.sync_run_as("tenant_b", "u2"):
        hits = memory_manager.recall("A 的", namespace=None)
        assert all(h.namespace.startswith("tenant_b") for h in hits)
        assert all("A 的" not in h.content for h in hits)


def test_same_namespace_still_isolated(memory_manager):
    """即使租户显式用相同 namespace，也隔离。"""
    tm = TenantManager()
    with tm.sync_run_as("a", "u1"):
        memory_manager.remember("x 数据", type=MemoryType.FACT, namespace="shared")
    with tm.sync_run_as("b", "u2"):
        memory_manager.remember("y 数据", type=MemoryType.FACT, namespace="shared")

    with tm.sync_run_as("a", "u1"):
        hits = memory_manager.recall("数据", namespace="shared")
        assert all("x" in h.content for h in hits)
        assert all("y" not in h.content for h in hits)


def test_no_tenant_uses_default(memory_manager):
    """无 tenant 上下文 → 默认 namespace，行为不变。"""
    memory_manager.remember("无租户记忆", type=MemoryType.FACT)
    hits = memory_manager.recall("无租户", namespace=None)
    assert len(hits) == 1
    assert memory_manager._resolve_namespace(None) == "default"
