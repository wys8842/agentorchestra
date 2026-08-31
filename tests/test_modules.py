"""core/session_store + 内置工具 + query_engine 测试"""

from symphony.core.message import Message
from symphony.core.session_store import SessionStore


class TestSessionStore:
    def test_save_and_load(self, tmp_path):
        store = SessionStore(session_dir=str(tmp_path / "sessions"))
        history = [Message("你好", "user"), Message("hi", "assistant")]

        filepath = store.save(
            agent_config={"name": "agent1", "llm_model": "gpt-4o"},
            history=history,
            tool_schema_hash="abc123",
            read_cache={},
            metadata={"total_tokens": 100, "total_steps": 2},
            session_name="test-session",
        )
        assert "test-session.json" in filepath

        data = store.load(filepath)
        assert data["agent_config"]["name"] == "agent1"
        assert len(data["history"]) == 2
        assert data["history"][0]["role"] == "user"
        assert data["metadata"]["total_tokens"] == 100
        assert data["tool_schema_hash"] == "abc123"

    def test_save_auto_name(self, tmp_path):
        store = SessionStore(session_dir=str(tmp_path / "s"))
        filepath = store.save(
            agent_config={}, history=[], tool_schema_hash="",
            read_cache={}, metadata={})
        assert "session-" in filepath

    def test_list_sessions(self, tmp_path):
        store = SessionStore(session_dir=str(tmp_path / "s"))
        store.save(agent_config={}, history=[], tool_schema_hash="",
                   read_cache={}, metadata={}, session_name="s1")
        store.save(agent_config={}, history=[], tool_schema_hash="",
                   read_cache={}, metadata={}, session_name="s2")
        sessions = store.list_sessions()
        assert len(sessions) == 2

    def test_delete(self, tmp_path):
        store = SessionStore(session_dir=str(tmp_path / "s"))
        store.save(agent_config={}, history=[], tool_schema_hash="",
                   read_cache={}, metadata={}, session_name="to-del")
        assert store.delete("to-del") is True
        assert store.delete("nonexistent") is False

    def test_config_consistency(self):
        store = SessionStore()
        result = store.check_config_consistency(
            {"llm_model": "gpt-4o"}, {"llm_model": "claude-3"})
        assert result["consistent"] is False
        assert len(result["warnings"]) == 1


class TestCalculator:
    def test_calculate(self):
        from symphony.tools.builtin.calculator import CalculatorTool, calculate
        resp = calculate("1+1")
        assert resp.status.value == "success"
        assert resp.data["result"] == 2

        tool = CalculatorTool()
        params = tool.get_parameters()
        assert params[0].name in ("expression", "input")

        resp = tool.run({"expression": "2*3"})
        assert resp.status.value == "success"


class TestSkillTool:
    def test_skill_not_found(self, tmp_path):
        from pathlib import Path

        from symphony.skills.loader import SkillLoader
        from symphony.tools.builtin.skill_tool import SkillTool

        loader = SkillLoader(skills_dir=Path(str(tmp_path / "skills")))
        tool = SkillTool(skill_loader=loader)

        resp = tool.run({"skill": "nonexistent"})
        assert resp.status.value == "error"
        assert resp.error_info["code"] == "NOT_FOUND"


class TestTodoWrite:
    def test_todowrite_basic(self, tmp_path):
        from symphony.tools.builtin.todowrite_tool import TodoWriteTool
        tool = TodoWriteTool(project_root=str(tmp_path), persistence_dir=str(tmp_path / "todos"))
        params = tool.get_parameters()
        names = [p.name for p in params]
        assert "summary" in names and "todos" in names

        # 不完整参数 → 错误响应（不崩溃）
        resp = tool.run({"action": "create", "summary": "任务"})
        assert resp.status.value in ("success", "error")


class TestQueryEngine:
    def test_interface_query(self):
        from symphony.ontology import (
            GraphStore,
            Interface,
            ObjectStore,
            ObjectType,
            OntologyEngine,
            SecurityContext,
        )
        from symphony.tools.base import ToolParameter

        store = ObjectStore(graph=GraphStore())
        Truck = ObjectType("truck", "asset_id", properties=[
            ToolParameter(name="asset_id", type="string", description="ID", required=True),
            ToolParameter(name="location", type="string", description="位置", required=True),
        ])
        store.register_type(Truck)
        store.insert("truck", {"asset_id": "t1", "location": "仓库A"})
        store.insert("truck", {"asset_id": "t2", "location": "仓库B"})

        engine = OntologyEngine(object_store=store, security_ctx=SecurityContext("a", ["a"]))
        engine.register_object_type(Truck)
        iface = Interface("asset", required_properties=["asset_id", "location"])
        engine.register_interface(iface)
        engine.implement_interface("asset", "truck")

        results = engine.query.query_interface(iface)
        assert "truck" in results
        assert len(results["truck"]) == 2

    def test_object_set(self):
        from symphony.ontology import (
            GraphStore,
            ObjectStore,
            ObjectType,
            OntologyEngine,
            SecurityContext,
        )
        from symphony.tools.base import ToolParameter

        store = ObjectStore(graph=GraphStore())
        Customer = ObjectType("customer", "cid", properties=[
            ToolParameter(name="cid", type="string", description="ID", required=True),
            ToolParameter(name="region", type="string", description="地区", required=False),
        ])
        store.register_type(Customer)
        for i in range(5):
            store.insert("customer", {"cid": f"c{i}", "region": "华东" if i % 2 else "华北"})

        engine = OntologyEngine(object_store=store, security_ctx=SecurityContext("a", ["a"]))
        engine.register_object_type(Customer)

        result = engine.query.object_set("customer", limit=3)
        assert result["total"] == 5
        assert len(result["objects"]) == 3
