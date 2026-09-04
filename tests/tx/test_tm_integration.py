"""TransactionManager 兼容测试（M1 接入后旧 API 不破坏 + coordinator 模式）。"""


from agentorchestra.ontology.process.transaction import TransactionManager
from agentorchestra.tx import TransactionCoordinator


def test_legacy_saga_still_works():
    """默认（无 coordinator）：纯 saga 行为不变。"""
    tx = TransactionManager()
    inventory = {"stock": 10}
    tx.register("deduct",
                lambda p, c: inventory.__setitem__("stock", inventory["stock"] - p.get("qty", 1)),
                lambda p, c: inventory.__setitem__("stock", inventory["stock"] + p.get("qty", 1)))
    tx.register("fail", lambda p, c: (_ for _ in ()).throw(RuntimeError("failed")), lambda p, c: None)

    r = tx.execute([
        {"action": "deduct", "params": {"qty": 3}},
        {"action": "fail", "params": {}},
    ])
    assert r["success"] is False
    assert r["failed"] == "fail"
    assert "deduct" in r["compensated"]
    assert inventory["stock"] == 10


def test_legacy_unregistered_action():
    tx = TransactionManager()
    inv = {"s": 10}
    tx.register("deduct", lambda p, c: inv.__setitem__("s", inv["s"] - 1),
                lambda p, c: inv.__setitem__("s", inv["s"] + 1))
    r = tx.execute([
        {"action": "deduct"},
        {"action": "not_registered"},
    ])
    assert r["success"] is False
    assert r["failed"] == "not_registered"
    assert inv["s"] == 10


def test_coordinator_mode_sync():
    """启用 coordinator（in-memory store）后 execute() sync 桥接仍工作。"""
    coord = TransactionCoordinator()  # in-memory
    tx = TransactionManager(coordinator=coord)
    inv = {"stock": 10}
    tx.register("deduct",
                lambda p, c: inv.__setitem__("stock", inv["stock"] - p.get("qty", 1)),
                lambda p, c: inv.__setitem__("stock", inv["stock"] + p.get("qty", 1)))
    tx.register("fail", lambda p, c: (_ for _ in ()).throw(RuntimeError("余额不足")),
                lambda p, c: None)

    r = tx.execute([
        {"action": "deduct", "params": {"qty": 3}},
        {"action": "fail", "params": {"amount": 100}},
    ])
    assert r["success"] is False
    assert "deduct" in r["compensated"]
    assert inv["stock"] == 10
    assert r["engine"] == "coordinator"


def test_coordinator_mode_success():
    coord = TransactionCoordinator()
    tx = TransactionManager(coordinator=coord)
    calls = []
    tx.register("a", lambda p, c: calls.append("a"), None)
    tx.register("b", lambda p, c: calls.append("b"), None)
    r = tx.execute([{"action": "a"}, {"action": "b"}])
    assert r["success"] is True
    assert calls == ["a", "b"]


def test_set_coordinator_later():
    """构造后再 set_coordinator → 之后 execute 走 coordinator。"""
    tx = TransactionManager()
    inv = {"s": 0}
    tx.register("inc", lambda p, c: inv.__setitem__("s", inv["s"] + 1),
                lambda p, c: inv.__setitem__("s", inv["s"] - 1))
    # 旧模式
    tx.execute([{"action": "inc"}])
    assert inv["s"] == 1
    # 启用 coordinator（自动同步已注册动作）
    tx.set_coordinator(TransactionCoordinator())
    # 手动重置状态后走新引擎
    inv["s"] = 0
    r = tx.execute([{"action": "inc"}])
    assert r["success"] is True
    assert r["engine"] == "coordinator"
    assert inv["s"] == 1
