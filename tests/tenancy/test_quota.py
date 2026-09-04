"""QuotaManager 测试：set_limit / charge / QuotaExceeded（优雅）。"""

import pytest

from agentorchestra.tenancy import QuotaExceeded, QuotaManager


def test_unlimited_by_default():
    qm = QuotaManager()
    q = qm.get("t1")
    assert q.limit == -1
    assert q.unlimited is True
    qm.charge("t1", 10000)  # 不限不抛
    assert qm.get("t1").used == 10000


def test_set_limit_and_charge():
    qm = QuotaManager()
    qm.set_limit("acme", 100)
    qm.charge("acme", 60)
    assert qm.get("acme").used == 60
    assert qm.get("acme").remaining() == 40


def test_charge_exceeds_raises():
    qm = QuotaManager()
    qm.set_limit("acme", 100)
    qm.charge("acme", 60)
    with pytest.raises(QuotaExceeded):
        qm.charge("acme", 60)  # 60+60 > 100
    # 恰好不超
    qm.charge("acme", 40)
    assert qm.get("acme").used == 100


def test_quota_exceeded_fields():
    qm = QuotaManager()
    qm.set_limit("acme", 50)
    qm.charge("acme", 30)
    try:
        qm.charge("acme", 30)
        assert False, "应抛"
    except QuotaExceeded as e:
        assert e.tenant_id == "acme"
        assert e.limit == 50
        assert e.used == 30
        assert "acme" in str(e)


def test_reset():
    qm = QuotaManager()
    qm.set_limit("acme", 10)
    qm.charge("acme", 8)
    qm.reset("acme")
    assert qm.get("acme").used == 0


def test_snapshot():
    qm = QuotaManager()
    qm.set_limit("a", 100)
    qm.set_limit("b", 50)
    qm.charge("a", 20)
    snap = qm.snapshot()
    assert snap["a"]["used"] == 20
    assert snap["b"]["limit"] == 50


def test_negative_tokens_noop():
    qm = QuotaManager()
    qm.charge("t", -5)
    assert qm.get("t").used == 0
