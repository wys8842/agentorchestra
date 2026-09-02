# -*- coding: utf-8 -*-
"""ecommerce_ontology.py 与 ontology_full.py 的单元测试

把示例的核心功能点拆成可断言的单测：
A. ecommerce：对象定义/动作规则/副作用/函数/接口/mount/规则拦截/动态扩展
B. ontology_full：类层次/派生属性/词汇/过滤/聚合/链接/物化/权限/审计/分支/工作流/事务/查询引擎/调度
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, 'D:/proj/agentorchestra')

from agentorchestra.ontology import (
    ActionType,
    Function,
    GraphStore,
    Interface,
    LinkType,
    MaterializationTarget,
    ObjectStore,
    ObjectType,
    OntologyEngine,
    SecurityContext,
    SQLiteBackend,
    StepNode,
    Workflow,
)
from agentorchestra.tools.base import ToolParameter
from agentorchestra.tools.registry import ToolRegistry

# ==================== 共享构建函数 ====================

def build_ecommerce(monkeypatch=None):
    """构建电商域引擎（对应 ecommerce_ontology.py）"""
    inventory = {"P1": 100, "P2": 50}

    Customer = ObjectType("customer", "customer_id", properties=[
        ToolParameter(name="customer_id", type="string", description="ID", required=True),
        ToolParameter(name="name", type="string", description="名", required=True),
        ToolParameter(name="tier", type="string", description="等级", default="standard"),
    ])
    Order = ObjectType("order", "order_id", properties=[
        ToolParameter(name="order_id", type="string", description="ID", required=True),
        ToolParameter(name="customer_id", type="string", description="客户", required=True),
        ToolParameter(name="amount", type="number", description="金额", required=True),
        ToolParameter(name="status", type="string", description="状态", default="pending"),
    ], link_types=[LinkType("belongs_to", "order", "customer")])

    def check_stock(params, ctx):
        if inventory.get(params.get("product_id", ""), 0) < params.get("qty", 1):
            return "库存不足"
        return None

    def check_amount(params, ctx):
        if params.get("amount", 0) <= 0:
            return "金额必须为正"
        return None

    def do_create_order(params, ctx):
        return ctx["object_store"].insert("order", {
            "order_id": params["order_id"], "customer_id": params["customer_id"],
            "amount": params["amount"], "status": "pending"})

    effects = []
    def notify(result, ctx):
        effects.append(result["order_id"])

    CreateOrder = ActionType("create_order", parameters=[
        ToolParameter(name="order_id", type="string", description="ID", required=True),
        ToolParameter(name="customer_id", type="string", description="客户", required=True),
        ToolParameter(name="product_id", type="string", description="商品", required=True),
        ToolParameter(name="qty", type="integer", description="数量", required=True),
        ToolParameter(name="amount", type="number", description="金额", required=True),
    ], rules=[check_stock, check_amount], execute_fn=do_create_order,
       side_effects=[notify])

    def do_pay(params, ctx):
        order_id = params["order_id"]
        ctx["object_store"].update("order", order_id, {"status": "paid"})
        inventory[params["product_id"]] -= params["qty"]
        return {"order_id": order_id, "status": "paid",
                "remaining_stock": inventory[params["product_id"]]}

    def rule_pending(params, ctx):
        order = ctx["object_store"].get("order", params["order_id"])
        return None if order and order.get("status") == "pending" else "订单状态不是 pending"

    PayOrder = ActionType("pay_order", parameters=[
        ToolParameter(name="order_id", type="string", description="ID", required=True),
        ToolParameter(name="product_id", type="string", description="商品", required=True),
        ToolParameter(name="qty", type="integer", description="数量", required=True),
    ], rules=[rule_pending], execute_fn=do_pay)

    engine = OntologyEngine(object_store=ObjectStore(graph=GraphStore()),
                            security_ctx=SecurityContext("admin", ["admin"]))
    for t in [Customer, Order]:
        engine.register_object_type(t)
    engine.register_action(CreateOrder)
    engine.register_action(PayOrder)
    engine.allow(["admin"], resource="*", action="*")
    return engine, CreateOrder, PayOrder, inventory, effects


def build_full(monkeypatch=None, tmp_dir=None):
    """构建全功能引擎（对应 ontology_full.py）"""
    db_path = str(Path(tmp_dir) / "demo.db") if tmp_dir else ":memory:"

    System = ObjectType("system", "id", properties=[
        ToolParameter(name="id", type="string", description="ID", required=True),
        ToolParameter(name="name", type="string", description="名", required=True),
    ])
    Module = ObjectType("module", "id", properties=[
        ToolParameter(name="id", type="string", description="ID", required=True),
        ToolParameter(name="name", type="string", description="名", required=True),
        ToolParameter(name="owner", type="string", description="负责人", required=False),
        ToolParameter(name="amount", type="number", description="金额", required=False),
        ToolParameter(name="total", type="number", description="总额", required=False),
    ], parent_type="system", derived_properties=["total"],
       link_types=[LinkType("belongs_to", "module", "project")])
    Project = ObjectType("project", "pid", properties=[
        ToolParameter(name="pid", type="string", description="ID", required=True),
        ToolParameter(name="name", type="string", description="名", required=True),
    ])

    backend = SQLiteBackend(db_path) if tmp_dir else None
    engine = OntologyEngine(
        object_store=ObjectStore(graph=GraphStore(), backend=backend),
        security_ctx=SecurityContext("admin", ["admin"]))
    engine.register_object_type(System)
    engine.register_object_type(Module)
    engine.register_object_type(Project)
    return engine, backend


# ==================== A. ecommerce 单元测试 ====================

class TestEcommerceObjectType:
    def test_object_type_definition(self):
        e, _, _, _, _ = build_ecommerce()
        ct = e.object_types["customer"]
        assert ct.primary_key == "customer_id"
        assert [p.name for p in ct.get_properties()] == ["customer_id", "name", "tier"]
        assert "name" in [p.name for p in ct.required_properties()]
        # tier 有默认值不算必填
        assert "tier" not in [p.name for p in ct.required_properties()]

    def test_link_type(self):
        e, _, _, _, _ = build_ecommerce()
        order = e.object_types["order"]
        assert "belongs_to" in [link.name for link in order.get_link_types()]


class TestEcommerceActions:
    def test_create_order_success(self):
        e, _, _, _, effects = build_ecommerce()
        r = e.actions["create_order"].execute(
            {"order_id": "o1", "customer_id": "c1", "product_id": "P1",
             "qty": 2, "amount": 99.0},
            {"object_store": e.object_store})
        assert r["success"] is True
        assert e.object_store.get("order", "o1")["status"] == "pending"
        assert effects == ["o1"]  # 副作用触发

    def test_create_order_stock_rule(self):
        e, _, _, _, _ = build_ecommerce()
        r = e.actions["create_order"].execute(
            {"order_id": "o2", "customer_id": "c1", "product_id": "P2",
             "qty": 999, "amount": 50.0},
            {"object_store": e.object_store})
        assert r["success"] is False
        assert "库存不足" in r["errors"]

    def test_create_order_amount_rule(self):
        e, _, _, _, _ = build_ecommerce()
        r = e.actions["create_order"].execute(
            {"order_id": "o3", "customer_id": "c1", "product_id": "P1",
             "qty": 1, "amount": -5.0},
            {"object_store": e.object_store})
        assert r["success"] is False
        assert "金额必须为正" in r["errors"]

    def test_pay_order_success_deducts_stock(self):
        e, _, _, inventory, _ = build_ecommerce()
        e.actions["create_order"].execute(
            {"order_id": "o1", "customer_id": "c1", "product_id": "P1",
             "qty": 2, "amount": 99.0}, {"object_store": e.object_store})
        before = inventory["P1"]
        r = e.actions["pay_order"].execute(
            {"order_id": "o1", "product_id": "P1", "qty": 2},
            {"object_store": e.object_store})
        assert r["success"] is True
        assert inventory["P1"] == before - 2  # 扣库存

    def test_pay_order_rejects_non_pending(self):
        e, _, _, _, _ = build_ecommerce()
        e.actions["create_order"].execute(
            {"order_id": "o1", "customer_id": "c1", "product_id": "P1",
             "qty": 2, "amount": 99.0}, {"object_store": e.object_store})
        # 先支付成功
        e.actions["pay_order"].execute(
            {"order_id": "o1", "product_id": "P1", "qty": 2},
            {"object_store": e.object_store})
        # 再支付应失败
        r = e.actions["pay_order"].execute(
            {"order_id": "o1", "product_id": "P1", "qty": 2},
            {"object_store": e.object_store})
        assert r["success"] is False
        assert "pending" in r["errors"][0]


class TestEcommerceFunctions:
    def test_compute_total(self):
        f = Function("compute_total", impl=lambda a, c: {"with_tax": round(a.get("amount", 0) * 1.13, 2)},
                     arguments=[ToolParameter(name="amount", type="number", description="金额", required=True)])
        r = f.call({"amount": 99.0})
        assert r["with_tax"] == 111.87


class TestEcommerceInterface:
    def test_interface_mount(self):
        e, _, _, _, _ = build_ecommerce()
        iface = Interface("payable", required_properties=["amount", "status"])
        e.register_interface(iface)
        e.implement_interface("payable", "order")
        assert iface.get_implementations() == ["order"]

    def test_mount_generates_tools(self):
        e, _, _, _, _ = build_ecommerce()
        registry = ToolRegistry()
        mounted = e.mount(registry)
        assert "QueryCustomer" in mounted
        assert "create_order" in mounted


class TestEcommerceDynamic:
    def test_dynamic_object_type(self):
        e, _, _, _, _ = build_ecommerce()
        promo = ObjectType("promo_product", "product_id", properties=[
            ToolParameter(name="product_id", type="string", description="ID", required=True),
            ToolParameter(name="discount", type="number", description="折扣", required=True)])
        e.register_object_type(promo)
        e.object_store.register_type(promo)
        e.object_store.insert("promo_product", {"product_id": "D1", "discount": 0.8})
        assert e.object_store.count("promo_product") == 1
        assert "promo_product" in e.object_types


# ==================== B. ontology_full 单元测试 ====================

class TestFullHierarchy:
    def test_parent_type(self):
        e, _ = build_full()
        module = e.object_types["module"]
        assert module.parent_type == "system"

    def test_derived_property_rejected(self):
        e, _ = build_full()
        with pytest.raises(ValueError):
            e.object_store.insert("module", {"id": "m1", "name": "x", "total": 999})

    def test_derived_property_allowed_fields(self):
        e, _ = build_full()
        e.object_store.insert("module", {"id": "m1", "name": "x", "amount": 100})
        assert e.object_store.get("module", "m1")["amount"] == 100


class TestFullVocabulary:
    def test_unknown_properties(self):
        e, _ = build_full()
        unknown = e.unknown_properties("module", {"id": "m1", "bad": 1})
        assert "bad" in unknown


class TestFullStorage:
    def test_filter_gt(self):
        e, _ = build_full()
        for i in range(5):
            e.object_store.insert("module", {
                "id": f"m{i}", "name": f"模块{i}", "owner": "李四" if i % 2 else "张三",
                "amount": 100 * (i + 1)})
        gt = e.object_store.filter("module", {"amount": 200}, operators={"amount": "gt"})
        assert len(gt) == 3

    def test_aggregate_sum(self):
        e, _ = build_full()
        for i in range(5):
            e.object_store.insert("module", {
                "id": f"m{i}", "name": f"模块{i}", "owner": "李四" if i % 2 else "张三",
                "amount": 100 * (i + 1)})
        agg = e.object_store.aggregate("module", "owner", "sum", "amount")
        assert agg["张三"] == 100 + 300 + 500  # m0,m2,m4
        assert agg["李四"] == 200 + 400

    def test_sqlite_persistence(self, tmp_path):
        e, backend = build_full(tmp_dir=str(tmp_path))
        e.object_store.insert("module", {"id": "m1", "name": "持久化", "amount": 50})
        e.object_store.close()

        # 重开
        e2, _ = build_full(tmp_dir=str(tmp_path))
        assert e2.object_store.get("module", "m1")["name"] == "持久化"


class TestFullLink:
    def test_create_and_get_link(self):
        e, _ = build_full()
        e.object_store.insert("module", {"id": "m1", "name": "x", "amount": 10})
        e.object_store.insert("project", {"pid": "p1", "name": "项目"})
        e.object_store.create_link("module", "m1", "belongs_to", "project", "p1")
        links = e.object_store.get_links("module", "m1")
        assert len(links) == 1
        assert links[0]["to_type"] == "project"


class TestFullGovernance:
    def test_fine_grained_permission(self):
        e, _ = build_full()
        viewer = SecurityContext("viewer", ["viewer"])
        e.allow(["viewer"], resource="module", action="read")
        e.allow(["admin"], resource="*", action="*")
        assert e.security.check("module", "read", viewer) is True
        assert e.security.check("module", "write", viewer) is False
        assert e.security.check("module", "write", SecurityContext("admin", ["admin"])) is True

    def test_branch_rollback(self):
        e, _ = build_full()
        for i in range(3):
            e.object_store.insert("module", {"id": f"m{i}", "name": f"n{i}", "amount": 10})
        e.snapshot_branch("before")
        e.object_store.delete("module", "m1")
        assert e.object_store.count("module") == 2
        e.switch_branch("before")
        assert e.object_store.count("module") == 3


class TestFullMaterialization:
    def test_materialize(self):
        e, _ = build_full()
        written = []
        e.register_materialization(MaterializationTarget(
            "postgres", lambda op, t, obj, patch: (written.append(f"{op}:{t}") or True)))
        e.materialization.materialize("insert", "module", {"id": "m9"})
        assert written == ["insert:module"]


class TestFullWorkflow:
    def test_workflow_runs_steps(self):
        e, _ = build_full()

        def exec_log(params, ctx):
            return {"ok": True, "msg": params.get("msg")}

        e.register_action(ActionType("step_a", parameters=[
            ToolParameter(name="msg", type="string", description="消息", required=True)],
            execute_fn=exec_log))
        e.register_action(ActionType("step_b", parameters=[
            ToolParameter(name="msg", type="string", description="消息", required=True)],
            execute_fn=exec_log))

        wf = Workflow("pipeline")
        wf.add_node(StepNode("s1", "step_a", {"msg": "第一步"}), entry=True)
        wf.add_node(StepNode("s2", "step_b", {"msg": "第二步"}, depends_on=["s1"]))
        e.workflow.register_workflow(wf)
        r = e.workflow.run("pipeline", ctx={"object_store": e.object_store})
        assert r["success"] is True
        assert len(r["results"]) == 2


class TestFullTransaction:
    def test_saga_compensation(self):
        e, _ = build_full()
        inv = {"stock": 10}
        tx = e.transaction
        tx.register("扣库存", lambda p, c: inv.__setitem__("stock", inv["stock"] - p.get("qty", 1)),
                    lambda p, c: inv.__setitem__("stock", inv["stock"] + p.get("qty", 1)))
        tx.register("扣款", lambda p, c: (_ for _ in ()).throw(RuntimeError("余额不足")),
                    lambda p, c: None)
        r = tx.execute([
            {"action": "扣库存", "params": {"qty": 3}},
            {"action": "扣款", "params": {"amount": 100}},
        ])
        assert r["success"] is False
        assert "扣库存" in r["compensated"]
        assert inv["stock"] == 10  # 补偿恢复


class TestFullQueryEngine:
    def test_object_set_paging(self):
        e, _ = build_full()
        for i in range(5):
            e.object_store.insert("module", {
                "id": f"m{i}", "name": f"模块{i}", "owner": "张三",
                "amount": 100 * (i + 1)})
        oset = e.query.object_set("module", conditions={"owner": "张三"},
                                  sort_by="amount", descending=True, limit=2)
        assert oset["total"] == 5
        assert len(oset["objects"]) == 2
        assert oset["objects"][0]["amount"] == 500  # 降序第一个最大

    def test_describe_join(self):
        e, _ = build_full()
        e.object_store.insert("module", {"id": "m1", "name": "x", "amount": 10})
        e.object_store.insert("project", {"pid": "p1", "name": "项目"})
        e.object_store.create_link("module", "m1", "belongs_to", "project", "p1")
        joined = e.query.describe_join("module", "belongs_to", "project")
        assert len(joined) == 1
        assert joined[0]["to"]["pid"] == "p1"
