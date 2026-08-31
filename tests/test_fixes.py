"""全面审查修复后的回归测试"""

import pytest

from agentorchestra.ontology import (
    ActionType,
    ConditionNode,
    GraphStore,
    ObjectStore,
    ObjectType,
    OntologyEngine,
    SecurityContext,
    SQLiteBackend,
    StepNode,
    TransactionManager,
    Workflow,
)
from agentorchestra.tools.base import ToolParameter
from agentorchestra.tools.registry import ToolRegistry


def make_customer() -> ObjectType:
    return ObjectType("customer", "customer_id", properties=[
        ToolParameter(name="customer_id", type="string", description="ID", required=True),
        ToolParameter(name="name", type="string", description="名", required=True),
        ToolParameter(name="region", type="string", description="地区", required=False),
        ToolParameter(name="total", type="number", description="总额", required=False),
    ], derived_properties=["total"])


class TestWorkflowCondition:
    """H3: 条件节点只执行选中分支"""

    def _make_engine(self):
        store = ObjectStore(graph=GraphStore())
        Order = ObjectType("order", "order_id", properties=[
            ToolParameter(name="order_id", type="string", description="ID", required=True),
            ToolParameter(name="status", type="string", description="状态"),
        ])
        store.register_type(Order)
        engine = OntologyEngine(object_store=store, security_ctx=SecurityContext("a", ["a"]))
        engine.register_object_type(Order)

        def exec_create(params, ctx):
            oid = "o" + str(len(ctx["object_store"].list_objects("order")) + 1)
            ctx["object_store"].insert("order", {"order_id": oid, "status": "created"})
            return {"order_id": oid, "status": "created"}

        def exec_set(params, ctx):
            oid = params.get("order_id")
            ctx["object_store"].update("order", oid, {"status": params.get("status", "x")})
            return {"order_id": oid, "status": params.get("status", "x")}

        engine.register_action(ActionType("create_order", parameters=[ToolParameter(name="x", type="string", description="x")], execute_fn=exec_create))
        engine.register_action(ActionType("set_status", parameters=[
            ToolParameter(name="order_id", type="string", description="id", required=True),
            ToolParameter(name="status", type="string", description="s", required=True)], execute_fn=exec_set))
        return engine, store

    def test_condition_false_skips_if_true(self):
        engine, store = self._make_engine()
        # 条件返回 False → 走 if_false 分支 A，跳过 if_true 分支 B
        wf = Workflow("test_cond")
        wf.add_node(StepNode("s_create", "create_order", {"x": "i"}), entry=True)
        wf.add_node(StepNode("s_pay", "set_status", {"order_id": "$s_create.order_id", "status": "paid"}))
        wf.add_node(StepNode("s_ship", "set_status", {"order_id": "$s_create.order_id", "status": "shipped"}))
        wf.add_node(ConditionNode("cond", lambda ctx: False, if_true="s_ship", if_false="s_pay"))
        # s_pay/s_ship 依赖条件节点
        wf.nodes["s_pay"].depends_on = ["cond"]
        wf.nodes["s_ship"].depends_on = ["cond"]
        engine.workflow.register_workflow(wf)

        result = engine.workflow.run("test_cond", ctx={"object_store": store})
        assert result["success"] is True
        # 条件 False → 只执行 s_pay（if_false），s_ship（if_true）应跳过
        assert "s_pay" in result["results"]
        assert "s_ship" not in result["results"]
        assert store.list_objects("order")[0]["status"] == "paid"


class TestTransaction:
    """H4: 未注册动作触发补偿"""

    def test_unregistered_action_triggers_compensation(self):
        tx = TransactionManager()
        inv = {"s": 10}
        tx.register("deduct", lambda p, c: inv.__setitem__("s", inv["s"] - p.get("qty", 1)),
                    lambda p, c: inv.__setitem__("s", inv["s"] + p.get("qty", 1)))

        result = tx.execute([
            {"action": "deduct", "params": {"qty": 3}},
            {"action": "not_registered", "params": {}},
        ])
        assert result["success"] is False  # 不应假成功
        assert result["failed"] == "not_registered"
        assert "deduct" in result["compensated"]  # 已成功动作被补偿
        assert inv["s"] == 10  # 补偿恢复


class TestObjectStoreValidation:
    """M: update 校验 + 派生属性 + 图节点命名"""

    def test_update_rejects_unknown_field(self):
        store = ObjectStore(graph=GraphStore())
        store.register_type(make_customer())
        store.insert("customer", {"customer_id": "c1", "name": "张三"})
        with pytest.raises(ValueError):
            store.update("customer", "c1", {"unknown_field": 1})

    def test_update_rejects_type_error(self):
        store = ObjectStore(graph=GraphStore())
        store.register_type(make_customer())
        store.insert("customer", {"customer_id": "c1", "name": "张三"})
        with pytest.raises(ValueError):
            store.update("customer", "c1", {"region": 123})  # string 类型

    def test_insert_rejects_derived_property(self):
        store = ObjectStore(graph=GraphStore())
        store.register_type(make_customer())
        with pytest.raises(ValueError):
            store.insert("customer", {"customer_id": "c1", "name": "张三", "total": 100})

    def test_update_rejects_derived_property(self):
        store = ObjectStore(graph=GraphStore())
        store.register_type(make_customer())
        store.insert("customer", {"customer_id": "c1", "name": "张三"})
        with pytest.raises(ValueError):
            store.update("customer", "c1", {"total": 100})

    def test_graph_node_naming_consistent(self):
        store = ObjectStore(graph=GraphStore())
        Order = ObjectType("order", "order_id", properties=[
            ToolParameter(name="order_id", type="string", description="ID", required=True),
        ], link_types=[])
        store.register_type(make_customer())
        store.register_type(Order)
        store.insert("customer", {"customer_id": "c1", "name": "张三"})
        store.insert("order", {"order_id": "o1"})
        # 节点应为 type:pk 格式
        assert "customer:c1" in store.graph.list_nodes()
        assert "order:o1" in store.graph.list_nodes()
        assert "c1" not in store.graph.list_nodes()  # 无裸 pk 孤立节点


class TestSQLiteThreadSafety:
    """H5: SQLite 跨线程"""

    def test_cross_thread_access(self, tmp_path):
        import threading
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path)

        errors = []

        def write():
            try:
                backend.put("customer", "c1", {"customer_id": "c1"})
            except Exception as e:
                errors.append(str(e))

        t = threading.Thread(target=write)
        t.start()
        t.join()

        assert errors == []  # 不应抛 ProgrammingError
        assert backend.get("customer", "c1") is not None
        backend.close()


class TestSQLiteCloseGuard:
    """M: close 后复用有防护"""

    def test_close_then_use_raises(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path)
        backend.close()
        with pytest.raises(RuntimeError):
            backend.put("customer", "c1", {"customer_id": "c1"})


class TestSchedulerOnceEnabled:
    """M: once 任务尊重 enabled"""

    def test_disabled_once_not_executed(self):
        import time

        from agentorchestra.ontology.process.scheduler import Scheduler
        sched = Scheduler()
        calls = []
        sched.add_once("t1", lambda p: calls.append(1), delay_seconds=0.1)
        sched._tasks["t1"].enabled = False
        sched.start()
        time.sleep(0.4)
        sched.stop()
        assert len(calls) == 0


class TestToolFilterFunctions:
    """M: _apply_tool_filter 处理函数工具"""

    def test_filter_disables_function_tools(self):
        from agentorchestra.core.agent import Agent
        from agentorchestra.tools.tool_filter import CustomFilter

        registry = ToolRegistry()
        registry.register_function(lambda x: x, name="secret_func")

        # 最小具体 Agent 子类（实现抽象方法 run）
        class MiniAgent(Agent):
            def run(self, input_text, **kwargs):
                return ""

        agent = MiniAgent.__new__(MiniAgent)
        agent.tool_registry = registry

        # 只允许不存在的工具 → secret_func 应被禁用
        flt = CustomFilter(allowed=["nothing"], mode="whitelist")
        original = agent._apply_tool_filter(flt)
        assert "secret_func" not in registry.list_tools()
        assert registry.get_function("secret_func") is None

        # 恢复
        agent._restore_tools(original)
        assert registry.get_function("secret_func") is not None
