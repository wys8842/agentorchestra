"""LLM 配额集成测试：tenant context 下 invoke 触发 charge；无 tenant 不计费。

不真调 adapter——构造 LLM 后用 monkeypatch 拦 `_adapter.invoke`。
"""

import pytest

from agentorchestra.core.llm import SymphonyLLM
from agentorchestra.tenancy import QuotaManager, TenantManager


def _make_llm(quota_manager=None, usage_recorder=None) -> SymphonyLLM:
    llm = object.__new__(SymphonyLLM)
    # 仅初始化 M6 相关 + charge 需要的属性
    llm.quota_manager = quota_manager
    llm.usage_recorder = usage_recorder
    llm.model = "mock"
    return llm


def test_charge_with_tenant_context():
    from agentorchestra.tenancy import QuotaExceeded

    llm = _make_llm(quota_manager=QuotaManager())
    llm.quota_manager.set_limit("acme", 100)
    tm = TenantManager()
    with tm.sync_run_as("acme"):
        llm._charge_and_record(60, 10.0)
        assert llm.quota_manager.get("acme").used == 60
        with pytest.raises(QuotaExceeded):
            llm._charge_and_record(60, 10.0)  # 超限 → QuotaExceeded


def test_charge_exceeded_raises():
    from agentorchestra.tenancy import QuotaExceeded

    llm = _make_llm(quota_manager=QuotaManager())
    llm.quota_manager.set_limit("acme", 100)
    tm = TenantManager()
    with tm.sync_run_as("acme"):
        llm._charge_and_record(100, 5.0)
        with pytest.raises(QuotaExceeded):
            llm._charge_and_record(1, 5.0)


def test_no_tenant_no_charge():
    """无 tenant context → 不计数（向后兼容）。"""
    qm = QuotaManager()
    qm.set_limit("acme", 10)
    llm = _make_llm(quota_manager=qm)
    llm._charge_and_record(50, 5.0)  # 无 context → 直接 return
    assert qm.get("acme").used == 0


def test_usage_recorded_with_tenant():
    from agentorchestra.tenancy import UsageRecorder

    ur = UsageRecorder()
    llm = _make_llm(usage_recorder=ur)
    tm = TenantManager()
    with tm.sync_run_as("acme", "alice"):
        llm._charge_and_record(42, 12.3)
    assert ur.total("acme") == 42
