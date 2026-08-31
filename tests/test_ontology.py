"""ontology 企业级 Ontology 测试"""
import pytest

from agentorchestra.ontology import (
    ActionType,
    GraphStore,
    Interface,
    ObjectStore,
    ObjectType,
    OntologyEngine,
    SecurityContext,
    StepNode,
    TransactionManager,
    Workflow,
)
from agentorchestra.tools.base import ToolParameter


def make_customer() -> ObjectType:
    return ObjectType("customer", "customer_id", properties=[
        ToolParameter(name="customer_id", type="string", description="ID", required=True),
        ToolParameter(name="name", type="string", description="名", required=True),
        ToolParameter(name="region", type="string", description="地区", required=False),
    ])


class TestObjectType:
    def test_validate_valid(self):
        ct = make_customer()
        assert ct.validate_object({"customer_id": "c1", "name": "张三"}) == []

    def test_validate_missing_primary_key(self):
        ct = make_customer()
        errors = ct.validate_object({"name": "张三"})
        assert any("主键" in e for e in errors)

    def test_validate_unknown_property(self):
        ct = make_customer()
        errors = ct.validate_object({"customer_id": "c1", "name": "张三", "bad": 1})
        assert any("未在对象类型" in e for e in errors)

    def test_validate_missing_required(self):
        ct = make_customer()
        errors = ct.validate_object({"customer_id": "c1"})
        assert any("name" in e for e in errors)


class TestObjectStore:
    def test_insert_and_get(self):
        store = ObjectStore(graph=GraphStore())
        store.register_type(make_customer())
        store.insert("customer", {"customer_id": "c1", "name": "张三"})
        obj = store.get("customer", "c1")
        assert obj["name"] == "张三"

    def test_insert_validation_error(self):
        store = ObjectStore(graph=GraphStore())
        store.register_type(make_customer())
        with pytest.raises(ValueError):
            store.insert("customer", {"name": "张三"})  # 缺主键

    def test_search_filter_aggregate(self):
        store = ObjectStore(graph=GraphStore())
        store.register_type(make_customer())
        store.insert("customer", {"customer_id": "c1", "name": "张三", "region": "华东"})
        store.insert("customer", {"customer_id": "c2", "name": "李四", "region": "华北"})
        store.insert("customer", {"customer_id": "c3", "name": "王五", "region": "华东"})

        assert len(store.search("customer", "张")) == 1
        assert len(store.filter("customer", {"region": "华东"})) == 2
        assert store.aggregate("customer", "region") == {"华东": 2, "华北": 1}


class TestActionType:
    def test_execute_success(self):
        store = ObjectStore(graph=GraphStore())
        store.register_type(make_customer())

        def exec_create(params, ctx):
            return ctx["object_store"].insert("customer", params)

        action = ActionType("create_customer", parameters=[
            ToolParameter(name="customer_id", type="string", description="ID", required=True),
            ToolParameter(name="name", type="string", description="名", required=True),
        ], execute_fn=exec_create)

        result = action.execute(
            {"customer_id": "c1", "name": "张三"},
            {"object_store": store})
        assert result["success"] is True

    def test_execute_missing_param(self):
        action = ActionType("create_customer", parameters=[
            ToolParameter(name="customer_id", type="string", description="ID", required=True),
        ])
        result = action.execute({}, {})
        assert result["success"] is False
        assert any("customer_id" in e for e in result["errors"])

    def test_execute_rule_reject(self):
        def rule(params, ctx):
            return None if params.get("amount", 0) > 0 else "金额必须为正"

        action = ActionType("x", parameters=[
            ToolParameter(name="amount", type="number", description="金额", required=True),
        ], rules=[rule])
        result = action.execute({"amount": -5}, {})
        assert result["success"] is False
        assert "金额必须为正" in result["errors"]


class TestOntologyEngine:
    def test_mount_generates_tools(self):
        engine = OntologyEngine(security_ctx=SecurityContext("admin", ["admin"]))
        engine.register_object_type(make_customer())
        engine.allow(["admin"], resource="*", action="*")

        from agentorchestra.tools.registry import ToolRegistry
        registry = ToolRegistry()
        mounted = engine.mount(registry)
        assert "QueryCustomer" in mounted
        assert registry.get_tool("QueryCustomer") is not None

    def test_permission_check(self):
        engine = OntologyEngine(security_ctx=SecurityContext("admin", ["admin"]))
        engine.allow(["admin"], resource="*", action="*")
        assert engine.security.check("customer", "write", SecurityContext("admin", ["admin"]))
        assert not engine.security.check("customer", "write", SecurityContext("viewer", ["viewer"]))

    def test_interface_implementation(self):
        engine = OntologyEngine()
        truck = ObjectType("truck", "asset_id", properties=[
            ToolParameter(name="asset_id", type="string", description="ID", required=True),
            ToolParameter(name="location", type="string", description="位置", required=True),
        ])
        iface = Interface("asset", required_properties=["asset_id", "location"])
        engine.register_object_type(truck)
        engine.register_interface(iface)
        engine.implement_interface("asset", "truck")
        assert iface.get_implementations() == ["truck"]


class TestWorkflow:
    def test_topological_execution(self):
        store = ObjectStore(graph=GraphStore())
        Order = ObjectType("order", "order_id", properties=[
            ToolParameter(name="order_id", type="string", description="ID", required=True),
            ToolParameter(name="status", type="string", description="状态"),
        ])
        store.register_type(Order)

        def exec_create(params, ctx):
            oid = "o" + str(len(ctx["object_store"].list_objects("order")) + 1)
            ctx["object_store"].insert("order", {"order_id": oid, "status": "created"})
            return {"order_id": oid, "status": "created"}

        def exec_pay(params, ctx):
            oid = params.get("order_id")
            ctx["object_store"].update("order", oid, {"status": "paid"})
            return {"order_id": oid, "status": "paid"}

        engine = OntologyEngine(object_store=store, security_ctx=SecurityContext("a", ["a"]))
        engine.register_object_type(Order)
        engine.register_action(ActionType("create_order", parameters=[ToolParameter(name="x", type="string", description="x")], execute_fn=exec_create))
        engine.register_action(ActionType("pay_order", parameters=[ToolParameter(name="order_id", type="string", description="id", required=True)], execute_fn=exec_pay))

        wf = Workflow("fulfill")
        wf.add_node(StepNode("s1", "create_order", {"x": "i"}), entry=True)
        wf.add_node(StepNode("s2", "pay_order", {"order_id": "$s1.order_id"}, depends_on=["s1"]))
        engine.workflow.register_workflow(wf)

        result = engine.workflow.run("fulfill", ctx={"object_store": store})
        assert result["success"] is True
        assert "s1" in result["results"] and "s2" in result["results"]
        assert store.list_objects("order")[0]["status"] == "paid"


class TestTransaction:
    def test_saga_compensation(self):
        tx = TransactionManager()
        inventory = {"stock": 10}

        tx.register(
            "deduct",
            lambda p, c: inventory.__setitem__("stock", inventory["stock"] - p.get("qty", 1)),
            lambda p, c: inventory.__setitem__("stock", inventory["stock"] + p.get("qty", 1)),
        )
        tx.register(
            "fail",
            lambda p, c: (_ for _ in ()).throw(RuntimeError("failed")),
            lambda p, c: None,
        )

        result = tx.execute([
            {"action": "deduct", "params": {"qty": 3}},
            {"action": "fail", "params": {}},
        ])
        assert result["success"] is False
        assert result["failed"] == "fail"
        assert "deduct" in result["compensated"]
        assert inventory["stock"] == 10  # 补偿恢复

    def test_all_success_no_compensation(self):
        tx = TransactionManager()
        calls = []

        tx.register("a", lambda p, c: calls.append("a"), None)
        tx.register("b", lambda p, c: calls.append("b"), None)
        result = tx.execute([{"action": "a"}, {"action": "b"}])
        assert result["success"] is True
        assert result["compensated"] == []
