"""对象身份测试：insert 注入 version；update CAS 冲突 TxConflict；系统字段豁免。"""

import pytest

from agentorchestra.governance import ObjectCAS
from agentorchestra.ontology.semantic.object_type import ObjectType
from agentorchestra.ontology.storage.object_store import ObjectStore
from agentorchestra.tools.base import ToolParameter


def _store():
    """构造带 Order 类型的对象存储。"""
    from agentorchestra.ontology.semantic.object_type import ObjectType
    from agentorchestra.tools.base import ToolParameter

    ot = ObjectType(
        api_name="Order",
        primary_key="id",
        properties=[
            ToolParameter(name="id", type="string", description=""),
            ToolParameter(name="amount", type="number", description="", required=False),
            ToolParameter(name="customer", type="string", description="", required=False),
        ],
    )
    s = ObjectStore()
    s.register_type(ot)
    return s


def test_insert_injects_identity_fields():
    s = _store()
    obj = s.insert("Order", {"id": "o1", "amount": 100, "customer": "alice"})
    assert obj["version"] == 1
    assert obj["created_tx"] == "none"
    assert obj["last_modified_tx"] == "none"


def test_system_fields_validated_as_ok():
    """对象带 version 字段也能通过类型校验（豁免）。"""
    s = _store()
    obj = s.insert("Order", {"id": "o1", "version": 99})  # version 由引擎覆盖
    assert obj["version"] == 1  # 引擎注入优先，非 99


def test_update_increments_version():
    s = _store()
    s.insert("Order", {"id": "o1", "amount": 100})
    v1 = s.get("Order", "o1")["version"]
    obj = s.update("Order", "o1", {"amount": 150})
    assert obj["version"] == v1 + 1


def test_update_cas_conflict_raises():
    from agentorchestra.tx.context import TxConflict

    s = _store()
    s.insert("Order", {"id": "o1", "amount": 100})
    # 读到 version=1
    s.update("Order", "o1", {"amount": 150})  # 现在 version=2
    with pytest.raises(TxConflict):
        s.update("Order", "o1", {"amount": 200}, expected_version=1)


def test_update_cas_success():
    s = _store()
    s.insert("Order", {"id": "o1", "amount": 100})
    obj = s.update("Order", "o1", {"amount": 150}, expected_version=1)
    assert obj["amount"] == 150
    assert obj["version"] == 2


def test_object_cas_helpers():
    obj = {"id": "o1"}
    ObjectCAS.init(obj, "tx-1")
    assert obj["version"] == 1
    assert obj["created_tx"] == "tx-1"
    ObjectCAS.bump(obj, "tx-2")
    assert obj["version"] == 2
    assert ObjectCAS.version_of(obj) == 2
    assert ObjectCAS.check(obj, 2) is True
    assert ObjectCAS.check(obj, 1) is False
    stripped = ObjectCAS.strip_system_fields(obj)
    assert "version" not in stripped


def test_validate_exempts_system_fields():

    ot = ObjectType(
        api_name="T",
        primary_key="id",
        properties=[ToolParameter(name="id", type="string", description="")],
    )
    errs = ot.validate_object({"id": "1", "version": 3, "created_tx": "t"})
    assert errs == []
    assert ot.unknown_properties({"id": "1", "version": 3}) == []
